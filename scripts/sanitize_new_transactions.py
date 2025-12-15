import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app import create_app, db
from app.models import Transaction
from app.utils import setup_logging, log_audit

logger = setup_logging('sanitize_new_transactions')
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
            print("\n" + "="*80)
            print("SANITIZING NEWLY ADDED TRANSACTIONS")
            print("="*80 + "\n")

            # Get the 24 newly added transactions by their entryIds
            new_entry_ids = [
                '20251128000001', '20251128000002', '20251128000003',
                '20251128000004', '20251128000005', '20251128000006',
                '20251128000007', '20251128000009', '20251128000011',
                '20251128000013', '20251128000015', '20251128000017',
                '20251128000018', '20251128000019', '20251128000022',
                '20251128000024', '20251128000027', '20251128000031',
                '20251128000044', '20251128000045', '20251128000046',
                '20251128000048', '20251128000049', '20251212000001'
            ]

            new_transactions = Transaction.query.filter(
                Transaction.entryId.in_(new_entry_ids),
                Transaction.CID == 'unallocated',
                Transaction.status == 'pending'
            ).all()

            print(f"Found {len(new_transactions)} new transactions to sanitize\n")

            updated_count = 0
            failed_count = 0

            for txn in new_transactions:
                extracted_cid = extract_cid(txn)
                if extracted_cid and extracted_cid != txn.CID:
                    old_cid = txn.CID
                    txn.CID = extracted_cid
                    txn.status = 'ready_to_post'
                    db.session.commit()
                    log_audit(txn.entryId, 'CID_EXTRACTED', 'CID', old_cid, extracted_cid)
                    updated_count += 1
                    logger.info(f'Extracted CID {extracted_cid} for {txn.entryId}')
                    print(f"✅ {txn.entryId}: Extracted CID{extracted_cid} | R{txn.amount:.2f} | {txn.remittance_info[:50]}")
                else:
                    failed_count += 1
                    print(f"❌ {txn.entryId}: No CID found | R{txn.amount:.2f} | Ref: {txn.reference} | Info: {txn.remittance_info[:40]}")

            print("\n" + "="*80)
            print(f"SUMMARY:")
            print(f"  Successfully extracted CID: {updated_count}")
            print(f"  Could not extract CID:     {failed_count}")
            print(f"  Total processed:            {len(new_transactions)}")
            print("="*80 + "\n")

            logger.info(f'Sanitization complete: updated {updated_count} transactions, {failed_count} failed')

        except Exception as e:
            logger.error(f'Sanitization failed: {e}')
            print(f"\nERROR: {e}")

if __name__ == '__main__':
    main()
