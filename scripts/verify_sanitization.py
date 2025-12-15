import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from app import create_app, db
from app.models import Transaction

app = create_app()

with app.app_context():
    # Get the 24 newly added transactions
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

    transactions = Transaction.query.filter(
        Transaction.entryId.in_(new_entry_ids)
    ).order_by(Transaction.entryId).all()

    print("\n" + "="*80)
    print("SANITIZATION VERIFICATION - NEWLY ADDED TRANSACTIONS")
    print("="*80 + "\n")

    ready_to_post = 0
    pending = 0

    for txn in transactions:
        status_icon = "✅" if txn.status == 'ready_to_post' else "⏳"
        cid_display = f"CID{txn.CID}" if txn.CID != 'unallocated' else "unallocated"

        print(f"{status_icon} {txn.entryId} | {cid_display:15s} | {txn.status:15s} | R{txn.amount:>8.2f} | {txn.remittance_info[:40]}")

        if txn.status == 'ready_to_post':
            ready_to_post += 1
        else:
            pending += 1

    print("\n" + "="*80)
    print(f"SUMMARY:")
    print(f"  Ready to Post:  {ready_to_post} transactions")
    print(f"  Still Pending:  {pending} transactions")
    print(f"  Total:          {len(transactions)} transactions")
    print("="*80 + "\n")
