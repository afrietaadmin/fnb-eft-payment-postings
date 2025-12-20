import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from app import create_app, db
from app.models import Transaction
from app.utils import setup_logging, log_execution, log_audit
from app.config import Config
import requests

logger = setup_logging('sanitize_data')
app = create_app()

def fetch_uisp_eft_mappings():
    """
    Fetch all clients from UISP and extract their eftPaymentReferenceUsed attribute.

    Returns:
        dict: Mapping of eft_reference -> client_id (both uppercase)
    """
    try:
        url = f"{Config.UISP_BASE_URL}clients"
        headers = {
            "Content-Type": "application/json",
            Config.UISP_AUTHORIZATION: Config.UISP_API_KEY
        }

        logger.info(f'Fetching clients from UISP: {url}')
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        clients = response.json()
        eft_mappings = {}

        for client in clients:
            client_id = client.get("id")
            attributes = client.get("attributes", [])

            # Look for eftPaymentReferenceUsed attribute
            for attribute in attributes:
                if attribute.get("key") == "eftPaymentReferenceUsed":
                    reference = attribute.get("value")
                    if reference:
                        reference_upper = reference.upper()
                        eft_mappings[reference_upper] = str(client_id)
                        logger.info(f'Found EFT mapping: "{reference}" → Client {client_id}')
                        break

        logger.info(f'Fetched {len(eft_mappings)} EFT payment reference mappings from UISP')
        return eft_mappings

    except requests.exceptions.RequestException as e:
        logger.error(f'Error fetching UISP clients: {e}')
        return {}
    except Exception as e:
        logger.error(f'Error processing UISP EFT mappings: {e}')
        return {}

def extract_cid(transaction, eft_mappings):
    """
    Extract CID from transaction using three methods in order:
    1. Parse "CID" from reference field
    2. Parse "CID" from remittance_info field
    3. Match transaction reference against UISP eft_mappings

    Args:
        transaction: Transaction object
        eft_mappings: dict of {eft_reference: client_id} from UISP

    Returns:
        str: Extracted CID, or None if not found
    """
    reference = (transaction.reference or '').upper()
    remittance_info = (transaction.remittance_info or '').upper()

    # Method 1: Extract from reference text
    if 'CID' in reference:
        parts = reference.split('CID')
        if len(parts) > 1:
            cid_candidate = parts[1].strip()
            numeric_cid = ''.join(c for c in cid_candidate if c.isdigit())
            if numeric_cid:
                return numeric_cid

    # Method 2: Extract from remittance_info text
    if 'CID' in remittance_info:
        parts = remittance_info.split('CID')
        if len(parts) > 1:
            cid_candidate = parts[1].strip()
            numeric_cid = ''.join(c for c in cid_candidate if c.isdigit())
            if numeric_cid:
                return numeric_cid

    # Method 3: Match against UISP EFT payment references
    if reference and reference in eft_mappings:
        cid = eft_mappings[reference]
        logger.info(f'Matched EFT reference "{transaction.reference}" to CID {cid}')
        return cid

    if remittance_info and remittance_info in eft_mappings:
        cid = eft_mappings[remittance_info]
        logger.info(f'Matched EFT remittance info "{transaction.remittance_info}" to CID {cid}')
        return cid

    return None

def main():
    with app.app_context():
        try:
            # Fetch EFT mappings from UISP BEFORE processing transactions
            logger.info('Fetching EFT payment reference mappings from UISP...')
            eft_mappings = fetch_uisp_eft_mappings()

            unallocated = Transaction.query.filter_by(CID='unallocated', status='pending').all()
            updated_count = 0
            text_parse_count = 0
            mapping_match_count = 0

            for txn in unallocated:
                extracted_cid = extract_cid(txn, eft_mappings)
                if extracted_cid and extracted_cid != txn.CID:
                    old_cid = txn.CID
                    txn.CID = extracted_cid
                    txn.status = 'ready_to_post'
                    db.session.commit()

                    # Track which method found the CID
                    method = 'TEXT_PARSE'
                    reference_upper = (txn.reference or '').upper()
                    remittance_upper = (txn.remittance_info or '').upper()

                    if (reference_upper in eft_mappings) or (remittance_upper in eft_mappings):
                        method = 'UISP_EFT_MAPPING'
                        mapping_match_count += 1
                    else:
                        text_parse_count += 1

                    log_audit(txn.entryId, 'CID_EXTRACTED', 'CID', old_cid, extracted_cid)
                    updated_count += 1
                    logger.info(f'Extracted CID {extracted_cid} for {txn.entryId} (method: {method})')

            summary = f'Updated {updated_count} transactions ({text_parse_count} text parse, {mapping_match_count} UISP EFT mappings)'
            logger.info(f'Sanitization complete: {summary}')
            log_execution('sanitize_data', 'SUCCESS', summary, transactions_processed=updated_count)

        except Exception as e:
            logger.error(f'Sanitization failed: {e}')
            log_execution('sanitize_data', 'FAILED', str(e))

if __name__ == '__main__':
    main()
