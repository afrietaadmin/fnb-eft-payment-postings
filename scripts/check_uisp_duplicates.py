import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

import requests
from datetime import datetime, timezone, timedelta
from app import create_app, db
from app.models import Transaction
from app.config import Config
from app.utils import setup_logging

logger = setup_logging('check_uisp_duplicates')
app = create_app()

def get_uisp_payments_for_client(cid, days_back=18):
    """Fetch payments from UISP for a specific client in the last N days"""
    try:
        today = datetime.now(timezone.utc)
        cutoff = today - timedelta(days=days_back)

        date_from = cutoff.strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')

        # Use v1.0 API endpoint with query parameters
        base_url = Config.UISP_BASE_URL.replace('/v2.0/', '/v1.0/')
        url = f"{base_url}payments?createdDateFrom={date_from}&createdDateTo={date_to}&clientId={cid}"

        headers = {
            Config.UISP_AUTHORIZATION: Config.UISP_API_KEY,
            'Content-Type': 'application/json'
        }

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            payments = response.json()
            # Sort by created date descending to get latest first
            payments_sorted = sorted(payments, key=lambda x: x.get('createdDate', ''), reverse=True)
            return payments_sorted
        else:
            logger.error(f'Failed to fetch UISP payments for CID {cid}: {response.status_code}')
            return []
    except Exception as e:
        logger.error(f'Error fetching UISP payments for CID {cid}: {e}')
        return []

def main():
    with app.app_context():
        try:
            DAYS_BACK = 18

            print("\n" + "="*80)
            print(f"CHECKING UISP FOR EXISTING PAYMENTS (LAST {DAYS_BACK} DAYS)")
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

            print(f"Checking {len(safe_transactions)} transactions against UISP...\n")

            safe_to_post = []
            duplicates_in_uisp = []
            api_errors = []

            for index, txn in enumerate(safe_transactions, 1):
                print(f"[{index}/{len(safe_transactions)}] Checking CID{txn.CID} (R{txn.amount:.2f})...", end=' ')

                try:
                    uisp_payments = get_uisp_payments_for_client(txn.CID, days_back=DAYS_BACK)

                    if uisp_payments:
                        # Check for matching amount
                        matching_payments = [p for p in uisp_payments if float(p.get('amount', 0)) == float(txn.amount)]

                        if matching_payments:
                            print(f"⚠️  DUPLICATE FOUND")
                            duplicates_in_uisp.append({
                                'transaction': txn,
                                'uisp_payments': matching_payments
                            })
                        else:
                            print(f"✅ Safe (different amounts in UISP)")
                            safe_to_post.append(txn)
                    else:
                        print(f"✅ Safe (no payments in UISP)")
                        safe_to_post.append(txn)

                except Exception as e:
                    print(f"❌ API Error")
                    logger.error(f'Error checking CID{txn.CID}: {e}')
                    api_errors.append({'transaction': txn, 'error': str(e)})

            # Display results
            print("\n" + "="*80)
            print("✅ SAFE TO POST (No matching payments in UISP)")
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
            print(f"⚠️  DUPLICATES IN UISP (Matching amount within last {DAYS_BACK} days)")
            print("="*80 + "\n")

            if duplicates_in_uisp:
                total_duplicate_amount = 0
                for item in duplicates_in_uisp:
                    txn = item['transaction']
                    uisp_payments = item['uisp_payments']

                    print(f"  ❌ {txn.entryId}")
                    print(f"     New Payment:      CID{txn.CID} | R{txn.amount:.2f} | Date: {txn.valueDate}")
                    print(f"     UISP Payments:    {len(uisp_payments)} matching payment(s)")

                    for p in uisp_payments:
                        created_date = datetime.fromisoformat(p['createdDate'].replace('Z', '+00:00'))
                        days_ago = (datetime.now(timezone.utc) - created_date).days
                        provider = p.get('providerName', 'N/A')
                        provider_id = p.get('providerPaymentId', 'N/A')
                        method = p.get('method', {}).get('name', 'Unknown')

                        print(f"       • R{p['amount']:.2f} | {created_date.strftime('%Y-%m-%d')} ({days_ago} days ago)")
                        print(f"         Method: {method} | Provider: {provider} | ID: {provider_id}")

                    print()
                    total_duplicate_amount += txn.amount

                print(f"  Total Duplicates: {len(duplicates_in_uisp)} transactions, R{total_duplicate_amount:.2f}")
            else:
                print("  (None)")

            if api_errors:
                print("\n" + "="*80)
                print("❌ API ERRORS")
                print("="*80 + "\n")
                for item in api_errors:
                    txn = item['transaction']
                    print(f"  {txn.entryId} | CID{txn.CID} | Error: {item['error']}")

            # Summary
            print("\n" + "="*80)
            print("SUMMARY")
            print("="*80)
            print(f"  Safe to Post:        {len(safe_to_post)} transactions")
            print(f"  Duplicates in UISP:  {len(duplicates_in_uisp)} transactions")
            print(f"  API Errors:          {len(api_errors)} transactions")
            print(f"  Total Checked:       {len(safe_transactions)} transactions")
            print(f"  UISP Query Window:   Last {DAYS_BACK} days")
            print("="*80 + "\n")

            if duplicates_in_uisp:
                print("⚠️  WARNING: Duplicates found in UISP!")
                print("These transactions should NOT be posted to avoid double-charging customers.\n")
            else:
                print("✅ No duplicates found in UISP - all transactions are safe to post!\n")

            logger.info(f'UISP duplicate check ({DAYS_BACK} days) complete: {len(safe_to_post)} safe, {len(duplicates_in_uisp)} duplicates, {len(api_errors)} errors')

        except Exception as e:
            logger.error(f'UISP duplicate check failed: {e}')
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    main()
