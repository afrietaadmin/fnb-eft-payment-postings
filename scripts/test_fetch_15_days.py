import sys
import os
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app import create_app, db
from app.models import Transaction
from app.config import Config
from app.utils import setup_logging

logger = setup_logging('test_fetch_15_days')
app = create_app()

def get_access_token():
    try:
        response = requests.post(
            Config.FNB_AUTH_URL,
            data={'grant_type': 'client_credentials'},
            auth=(Config.FNB_CLIENT_ID, Config.FNB_CLIENT_SECRET)
        )
        response.raise_for_status()
        logger.info('Access token obtained')
        return response.json()['access_token']
    except Exception as e:
        logger.error(f'Failed to get access token: {e}')
        raise

def fetch_transactions_for_account(access_token, account_number, days_back=15):
    sast = ZoneInfo('Africa/Johannesburg')
    now = datetime.now(sast)
    to_date = now.strftime('%Y-%m-%d')
    from_date = (now - timedelta(days=days_back)).strftime('%Y-%m-%d')

    headers = {
        'Authorization': f'Bearer {access_token}',
        'X-Request-ID': f"req-test-{datetime.now().strftime('%H%M%S')}"
    }
    params = {'fromDate': from_date, 'toDate': to_date}
    url = Config.FNB_BASE_URL + Config.FNB_TRANSACTION_HISTORY_URL.format(accountNumber=account_number)

    logger.info(f'Fetching {account_number} from {from_date} to {to_date}')

    all_entries = []
    page_number = 1

    try:
        while True:
            logger.info(f'Fetching page {page_number} for {account_number}')
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            # Collect entries from this page
            entries = data.get('entry', [])
            all_entries.extend(entries)
            logger.info(f'Page {page_number}: Retrieved {len(entries)} transactions (total so far: {len(all_entries)})')

            # Check pagination
            pagination = data.get('groupHeader', {}).get('pagination', {})
            last_page = pagination.get('lastPageIndicator', True)

            if last_page:
                logger.info(f'Reached last page for {account_number}. Total transactions: {len(all_entries)}')
                break

            # Get lastItemKey for next page
            last_item_key = pagination.get('lastItemKey')
            if not last_item_key:
                logger.warning(f'lastPageIndicator is False but no lastItemKey provided. Stopping pagination.')
                break

            # Add lastItemKey to params for next request
            params['lastItemKey'] = last_item_key
            page_number += 1

        return all_entries

    except Exception as e:
        logger.error(f'Failed to fetch transactions for {account_number}: {e}')
        return all_entries if all_entries else []

def analyze_missing_transactions(fetched_entries, account_number):
    """Compare fetched transactions with DB and identify missing ones"""
    excluded_terms_lower = {t.lower() for t in Config.EXCLUDED_TERMS}

    missing_transactions = []

    for entry in fetched_entries:
        try:
            entryId = entry.get('entryId')
            if not entryId:
                continue

            amount = float(entry.get('amount', {}).get('amount', 0))
            if amount < 0:
                continue

            remittance_info = entry.get('entryDetails', {}).get('transactionDetails', {}).get('remittanceInfo', {}).get('unstructured', '') or ''
            reference = entry.get('entryDetails', {}).get('transactionDetails', {}).get('reference', {}).get('endToEndId', '') or ''

            # Skip excluded terms
            if any(term in remittance_info.lower() for term in excluded_terms_lower) or any(term in reference.lower() for term in excluded_terms_lower):
                continue

            # Check if exists in DB by entryId
            existing = Transaction.query.filter_by(entryId=entryId).first()
            if existing:
                continue

            value_date = entry.get('valueDate', {}).get('Date', '')

            # Check for duplicates by amount + valueDate + account
            duplicate_by_data = Transaction.query.filter_by(
                account=account_number,
                amount=amount,
                valueDate=value_date
            ).first()

            if duplicate_by_data:
                continue

            # This transaction is missing from DB
            missing_transactions.append({
                'entryId': entryId,
                'account': account_number,
                'amount': amount,
                'valueDate': value_date,
                'remittance_info': remittance_info,
                'reference': reference
            })

        except Exception as e:
            logger.error(f'Error analyzing entry: {e}')

    return missing_transactions

def main():
    with app.app_context():
        try:
            print("\n" + "="*80)
            print("TEST MODE: Fetching last 15 days - NO DATABASE COMMITS")
            print("="*80 + "\n")

            # First, show current DB stats
            sast = ZoneInfo('Africa/Johannesburg')
            now = datetime.now(sast)
            date_15_days_ago = (now - timedelta(days=15)).strftime('%Y-%m-%d')

            current_count = Transaction.query.filter(Transaction.valueDate >= date_15_days_ago).count()
            print(f"Current DB transactions (last 15 days): {current_count}\n")

            token = get_access_token()
            accounts = [Config.FNB_ACCOUNT_NUMBER1, Config.FNB_ACCOUNT_NUMBER2]

            all_missing = []

            for account in accounts:
                print(f"\n--- Processing Account: {account} ---")
                entries = fetch_transactions_for_account(token, account, days_back=15)
                print(f"Total fetched from API: {len(entries)}")

                missing = analyze_missing_transactions(entries, account)
                all_missing.extend(missing)

                if missing:
                    print(f"\nMISSING TRANSACTIONS FOR {account}: {len(missing)}")
                    for txn in missing:
                        print(f"\n  EntryID: {txn['entryId']}")
                        print(f"  Date: {txn['valueDate']}")
                        print(f"  Amount: R{txn['amount']:.2f}")
                        print(f"  Reference: {txn['reference']}")
                        print(f"  Remittance: {txn['remittance_info']}")
                else:
                    print(f"No missing transactions for {account}")

            print("\n" + "="*80)
            print(f"SUMMARY: {len(all_missing)} missing transactions found")
            print("="*80 + "\n")

        except Exception as e:
            logger.error(f'Test failed: {e}')
            print(f"\nERROR: {e}")

if __name__ == '__main__':
    main()
