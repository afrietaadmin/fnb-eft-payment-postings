import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app import create_app, db
from app.models import Transaction

app = create_app()

with app.app_context():
    sast = ZoneInfo('Africa/Johannesburg')
    now = datetime.now(sast)
    date_15_days_ago = (now - timedelta(days=15)).strftime('%Y-%m-%d')

    total = Transaction.query.filter(Transaction.valueDate >= date_15_days_ago).count()

    print(f"\nTotal transactions (last 15 days): {total}")
    print(f"\nBreakdown by date:")
    print("-" * 40)

    # Get counts by date
    from sqlalchemy import func
    results = db.session.query(
        Transaction.valueDate,
        func.count(Transaction.id).label('count')
    ).filter(
        Transaction.valueDate >= date_15_days_ago
    ).group_by(
        Transaction.valueDate
    ).order_by(
        Transaction.valueDate
    ).all()

    for row in results:
        print(f"{row.valueDate}: {row.count} transactions")

    # Check specific dates we added
    print("\n" + "=" * 40)
    print("Newly added transactions on 2025-11-28:")
    print("=" * 40)

    new_txns = Transaction.query.filter(
        Transaction.valueDate == '2025-11-28',
        Transaction.entryId.in_([
            '20251128000001', '20251128000002', '20251128000003',
            '20251128000004', '20251128000005', '20251128000006',
            '20251128000007', '20251128000009', '20251128000011'
        ])
    ).all()

    for txn in new_txns:
        print(f"{txn.entryId}: R{txn.amount:.2f} - {txn.account} - {txn.remittance_info[:50]}")

    print(f"\nTotal new transactions found: {len(new_txns)}")
