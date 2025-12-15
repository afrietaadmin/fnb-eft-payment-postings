import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from datetime import datetime, timezone, timedelta
from app import create_app, db
from app.models import Transaction
from sqlalchemy import func

app = create_app()

def main():
    with app.app_context():
        print("\n" + "="*80)
        print("INVESTIGATING DUPLICATE DETECTION LOGIC")
        print("="*80 + "\n")

        # Get the 22 "safe to post" transactions
        safe_entry_ids = [
            '20251128000027', '20251128000019', '20251128000005', '20251128000009',
            '20251128000013', '20251128000045', '20251212000001', '20251128000003',
            '20251128000002', '20251128000022', '20251128000001', '20251128000049',
            '20251128000048', '20251128000006', '20251128000015', '20251128000018',
            '20251128000024', '20251128000011', '20251128000044', '20251128000017',
            '20251128000031', '20251128000046'
        ]

        safe_transactions = Transaction.query.filter(
            Transaction.entryId.in_(safe_entry_ids)
        ).order_by(Transaction.CID).all()

        print("Checking each 'safe to post' transaction for existing payments...\n")
        print("="*80)

        cutoff_17_days = datetime.now(timezone.utc) - timedelta(days=17)
        cutoff_30_days = datetime.now(timezone.utc) - timedelta(days=30)

        for txn in safe_transactions:
            print(f"\n📋 NEW: {txn.entryId} | CID{txn.CID} | R{txn.amount:.2f} | {txn.valueDate}")

            # Check all posted payments for this CID
            posted_payments = Transaction.query.filter(
                Transaction.CID == txn.CID,
                Transaction.posted == 'yes',
                Transaction.entryId != txn.entryId
            ).order_by(Transaction.postedDate.desc()).all()

            if posted_payments:
                print(f"   ⚠️  Found {len(posted_payments)} posted payment(s) for CID{txn.CID}:")
                for p in posted_payments:
                    if p.postedDate:
                        if p.postedDate.tzinfo is None:
                            posted_date = p.postedDate.replace(tzinfo=timezone.utc)
                        else:
                            posted_date = p.postedDate
                        days_ago = (datetime.now(timezone.utc) - posted_date).days

                        within_17 = "✓ Within 17 days" if posted_date >= cutoff_17_days else "✗ Older than 17 days"
                        same_amount = "✓ Same amount" if p.amount == txn.amount else f"✗ Different (R{p.amount:.2f})"

                        print(f"      • {p.entryId} | R{p.amount:.2f} | Posted: {p.postedDate.strftime('%Y-%m-%d')} ({days_ago} days ago)")
                        print(f"        {within_17} | {same_amount}")
                    else:
                        print(f"      • {p.entryId} | R{p.amount:.2f} | Posted: (no date) | posted='{p.posted}'")
            else:
                print(f"   ✅ No posted payments found for CID{txn.CID}")

            # Also check for pending/ready_to_post with same CID
            pending_payments = Transaction.query.filter(
                Transaction.CID == txn.CID,
                Transaction.posted == 'no',
                Transaction.entryId != txn.entryId
            ).all()

            if pending_payments:
                print(f"   📌 Found {len(pending_payments)} pending/unposted payment(s) for CID{txn.CID}:")
                for p in pending_payments:
                    print(f"      • {p.entryId} | R{p.amount:.2f} | Status: {p.status} | Date: {p.valueDate}")

        print("\n" + "="*80)
        print("CHECKING POSTED FIELD VALUES")
        print("="*80 + "\n")

        # Check what values exist in the 'posted' field
        posted_values = db.session.query(
            Transaction.posted,
            func.count(Transaction.id)
        ).group_by(Transaction.posted).all()

        print("Values in 'posted' field:")
        for value, count in posted_values:
            print(f"  '{value}': {count} transactions")

        print("\n" + "="*80)
        print("CHECKING POSTEDDATE FIELD")
        print("="*80 + "\n")

        # Check transactions marked as posted but missing postedDate
        posted_no_date = Transaction.query.filter(
            Transaction.posted == 'yes',
            Transaction.postedDate == None
        ).count()

        print(f"Transactions with posted='yes' but no postedDate: {posted_no_date}")

        if posted_no_date > 0:
            print("\n⚠️  WARNING: Some transactions are marked as posted but have no postedDate!")
            print("This could cause the duplicate detection to fail.\n")

if __name__ == '__main__':
    main()
