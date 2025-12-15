import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from app import create_app, db
from app.models import Transaction
from app.utils import setup_logging, log_execution, log_audit

logger = setup_logging('sanitize_data')
app = create_app()

def extract_cid(transaction):
    reference = (transaction.reference or '').upper()
    remittance_info = (transaction.remittance_info or '').upper()

    if 'CID' in reference:
        parts = reference.split('CID')
        if len(parts) > 1:
            cid_candidate = parts[1].strip()
            numeric_cid = ''.join(c for c in cid_candidate if c.isdigit())
            if numeric_cid:
                return numeric_cid

    if 'CID' in remittance_info:
        parts = remittance_info.split('CID')
        if len(parts) > 1:
            cid_candidate = parts[1].strip()
            numeric_cid = ''.join(c for c in cid_candidate if c.isdigit())
            if numeric_cid:
                return numeric_cid

    return None

def main():
    with app.app_context():
        try:
            unallocated = Transaction.query.filter_by(CID='unallocated', status='pending').all()
            updated_count = 0

            for txn in unallocated:
                extracted_cid = extract_cid(txn)
                if extracted_cid and extracted_cid != txn.CID:
                    old_cid = txn.CID
                    txn.CID = extracted_cid
                    txn.status = 'ready_to_post'
                    db.session.commit()
                    log_audit(txn.entryId, 'CID_EXTRACTED', 'CID', old_cid, extracted_cid)
                    updated_count += 1
                    logger.info(f'Extracted CID {extracted_cid} for {txn.entryId}')

            logger.info(f'Sanitization complete: updated {updated_count} transactions')
            log_execution('sanitize_data', 'SUCCESS', f'Updated {updated_count} transactions', transactions_processed=updated_count)

        except Exception as e:
            logger.error(f'Sanitization failed: {e}')
            log_execution('sanitize_data', 'FAILED', str(e))

if __name__ == '__main__':
    main()
