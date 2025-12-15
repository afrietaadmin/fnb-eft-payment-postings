import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from app import create_app, db
from app.models import Transaction

app = create_app()

def main():
    with app.app_context():
        print("\n" + "="*80)
        print("TRANSACTIONS MARKED AS POSTED BUT MISSING postedDate")
        print("="*80 + "\n")

        posted_no_date = Transaction.query.filter(
            Transaction.posted == 'yes',
            Transaction.postedDate == None
        ).order_by(Transaction.CID).all()

        print(f"Found {len(posted_no_date)} transactions with posted='yes' but no postedDate:\n")

        # Get the "safe to post" CIDs for comparison
        safe_cids = ['1003', '1022', '1033', '1111', '1118', '1256', '252', '289',
                     '345', '365', '371', '57', '571', '579', '745', '773', '788',
                     '816', '823', '865', '935', '959']

        matching_cids = []

        for txn in posted_no_date:
            is_match = "⚠️  MATCH" if txn.CID in safe_cids else ""
            print(f"{txn.entryId} | CID{txn.CID:5s} | R{txn.amount:>8.2f} | {txn.valueDate} | posted='{txn.posted}' | postedDate=None {is_match}")

            if txn.CID in safe_cids:
                matching_cids.append({
                    'entryId': txn.entryId,
                    'CID': txn.CID,
                    'amount': txn.amount,
                    'valueDate': txn.valueDate
                })

        if matching_cids:
            print("\n" + "="*80)
            print("⚠️  CRITICAL: DUPLICATES MISSED DUE TO MISSING postedDate")
            print("="*80 + "\n")

            print(f"Found {len(matching_cids)} posted payments (without dates) for CIDs we marked as 'safe to post':\n")

            for item in matching_cids:
                print(f"  CID{item['CID']:5s} | {item['entryId']} | R{item['amount']:.2f} | {item['valueDate']}")
                print(f"    ➜ This CID is in our 'safe to post' list but already has a posted payment!")

            print("\n" + "="*80)
            print("ROOT CAUSE IDENTIFIED")
            print("="*80)
            print("\nThe duplicate detection query uses:")
            print("  Transaction.postedDate >= cutoff")
            print("\nThis excludes transactions where postedDate is NULL, even if posted='yes'.")
            print("\nFIX: The duplicate check should use:")
            print("  (Transaction.postedDate >= cutoff) OR (Transaction.postedDate IS NULL)")
            print("="*80 + "\n")

        else:
            print("\n✅ No matches - the posted transactions without dates don't overlap with 'safe to post' CIDs")

if __name__ == '__main__':
    main()
