import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from datetime import datetime
from zoneinfo import ZoneInfo
from app import create_app, db
from app.models import Transaction, FailedTransaction
from app.utils import setup_logging, log_audit

logger = setup_logging('mark_uisp_duplicates')
app = create_app()

def main():
    with app.app_context():
        try:
            print("\n" + "="*80)
            print("MARKING UISP DUPLICATES IN DATABASE")
            print("="*80 + "\n")

            # All 22 transactions that need to be marked
            duplicate_entry_ids = [
                '20251128000027', '20251128000019', '20251128000005', '20251128000009',
                '20251128000013', '20251128000045', '20251212000001', '20251128000003',
                '20251128000002', '20251128000022', '20251128000001', '20251128000049',
                '20251128000048', '20251128000006', '20251128000015', '20251128000018',
                '20251128000024', '20251128000011', '20251128000044', '20251128000017',
                '20251128000031', '20251128000046'
            ]

            transactions = Transaction.query.filter(
                Transaction.entryId.in_(duplicate_entry_ids)
            ).all()

            print(f"Found {len(transactions)} transactions to mark as duplicates\n")

            marked_count = 0

            for txn in transactions:
                # Check if already in FailedTransaction
                existing_failed = FailedTransaction.query.filter_by(entryId=txn.entryId).first()

                if not existing_failed:
                    reason = f"Duplicate payment found in UISP: CID{txn.CID} already paid R{txn.amount:.2f} within last 18 days. Flagged for manual review."

                    failed_txn = FailedTransaction(
                        entryId=txn.entryId,
                        reason=reason,
                        error_code='DUPLICATE_UISP_MANUAL_REVIEW',
                        resolved=False
                    )
                    db.session.add(failed_txn)
                    marked_count += 1

                    log_audit(
                        txn.entryId,
                        'DUPLICATE_UISP',
                        'status',
                        txn.status,
                        'duplicate_manual_review',
                        'mark_uisp_duplicates_script'
                    )

                    print(f"✅ {txn.entryId} | CID{txn.CID:5s} | R{txn.amount:>8.2f} | Marked for manual review")
                else:
                    print(f"⏭️  {txn.entryId} | CID{txn.CID:5s} | R{txn.amount:>8.2f} | Already in FailedTransaction table")

                # Update transaction status
                txn.status = 'duplicate_manual_review'

            db.session.commit()

            print("\n" + "="*80)
            print("SUMMARY")
            print("="*80)
            print(f"  Added to FailedTransaction: {marked_count}")
            print(f"  Total transactions marked:  {len(transactions)}")
            print(f"  Status updated to:          'duplicate_manual_review'")
            print("="*80 + "\n")

            print("✅ All transactions flagged for manual review in GUI")
            print("   Error Code: DUPLICATE_UISP_MANUAL_REVIEW\n")

            logger.info(f'Marked {marked_count} UISP duplicates for manual review')

        except Exception as e:
            logger.error(f'Failed to mark duplicates: {e}')
            print(f"\nERROR: {e}")
            db.session.rollback()
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    main()
