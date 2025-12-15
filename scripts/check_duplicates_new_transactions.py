import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from datetime import datetime, timezone, timedelta
from app import create_app, db
from app.models import Transaction
from app.config import Config
from app.utils import setup_logging

logger = setup_logging('check_duplicates_new_transactions')
app = create_app()

def check_duplicate_payment(txn):
    """Check if this CID already has a posted payment in the last N days (configurable)"""
    if not txn.CID or txn.CID == 'unallocated':
        return None

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=Config.DUPLICATE_DETECTION_DAYS)

        # Find other posted payments for this CID in last N days
        duplicate = Transaction.query.filter(
            Transaction.CID == txn.CID,
            Transaction.posted == 'yes',
            Transaction.entryId != txn.entryId,  # Exclude current transaction
            Transaction.postedDate >= cutoff
        ).first()

        return duplicate
    except Exception as e:
        logger.error(f'Error checking duplicate for {txn.entryId}: {e}')
        return None

def main():
    with app.app_context():
        try:
            print("\n" + "="*80)
            print("DUPLICATE CHECK - NEWLY ADDED TRANSACTIONS (NO POSTING TO UISP)")
            print("="*80 + "\n")

            # Get the 24 newly added transactions that are ready to post
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
                Transaction.status == 'ready_to_post'
            ).order_by(Transaction.CID).all()

            print(f"Checking {len(new_transactions)} new transactions for duplicates...")
            print(f"Duplicate detection window: {Config.DUPLICATE_DETECTION_DAYS} days\n")

            safe_to_post = []
            duplicates_found = []
            no_cid = []

            for txn in new_transactions:
                if not txn.CID or txn.CID == 'unallocated':
                    no_cid.append(txn)
                    continue

                duplicate = check_duplicate_payment(txn)

                if duplicate:
                    duplicates_found.append({
                        'transaction': txn,
                        'duplicate': duplicate
                    })
                else:
                    safe_to_post.append(txn)

            # Display results
            print("="*80)
            print("✅ SAFE TO POST (No duplicates found)")
            print("="*80 + "\n")

            if safe_to_post:
                total_safe_amount = 0
                for txn in safe_to_post:
                    print(f"  {txn.entryId} | CID{txn.CID:5s} | R{txn.amount:>8.2f} | {txn.remittance_info[:45]}")
                    total_safe_amount += txn.amount
                print(f"\n  Total: {len(safe_to_post)} transactions, R{total_safe_amount:.2f}")
            else:
                print("  (None)")

            print("\n" + "="*80)
            print("⚠️  DUPLICATES DETECTED (Already posted within last 6 days)")
            print("="*80 + "\n")

            if duplicates_found:
                for item in duplicates_found:
                    txn = item['transaction']
                    dup = item['duplicate']
                    days_ago = (datetime.now(timezone.utc) - dup.postedDate).days

                    print(f"  ❌ {txn.entryId}")
                    print(f"     New Payment:      CID{txn.CID} | R{txn.amount:.2f} | {txn.valueDate}")
                    print(f"     Existing Posted:  {dup.entryId} | R{dup.amount:.2f} | {dup.postedDate.strftime('%Y-%m-%d')} ({days_ago} days ago)")
                    print(f"     Reason:           CID{txn.CID} already paid R{dup.amount:.2f} on {dup.postedDate.strftime('%Y-%m-%d')}")
                    print()
            else:
                print("  (None)")

            print("="*80)
            print("⏳ NO CID / UNALLOCATED")
            print("="*80 + "\n")

            if no_cid:
                for txn in no_cid:
                    print(f"  {txn.entryId} | {txn.CID:15s} | R{txn.amount:>8.2f} | {txn.remittance_info[:45]}")
            else:
                print("  (None)")

            # Summary
            print("\n" + "="*80)
            print("SUMMARY")
            print("="*80)
            print(f"  Safe to Post:        {len(safe_to_post)} transactions")
            print(f"  Duplicates Found:    {len(duplicates_found)} transactions")
            print(f"  No CID/Unallocated:  {len(no_cid)} transactions")
            print(f"  Total Checked:       {len(new_transactions)} transactions")
            print("="*80 + "\n")

            if duplicates_found:
                print("⚠️  WARNING: Duplicates detected!")
                print("These transactions should NOT be posted to avoid double-charging customers.\n")
            else:
                print("✅ No duplicates found - all transactions are safe to post!\n")

            logger.info(f'Duplicate check complete: {len(safe_to_post)} safe, {len(duplicates_found)} duplicates, {len(no_cid)} no CID')

        except Exception as e:
            logger.error(f'Duplicate check failed: {e}')
            print(f"\nERROR: {e}")

if __name__ == '__main__':
    main()
