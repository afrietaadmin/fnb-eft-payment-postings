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

logger = setup_logging('add_missing_transactions')
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
        'X-Request-ID': f"req-add-{datetime.now().strftime('%H%M%S')}"
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

def filter_and_store_transactions(entries, account_number):
    sast = ZoneInfo('Africa/Johannesburg')
    excluded_terms_lower = {t.lower() for t in Config.EXCLUDED_TERMS}
    new_count = 0

    for entry in entries:
        try:
            entryId = entry.get('entryId')
            if not entryId:
                logger.warning('Entry missing entryId, skipping')
                continue

            amount = float(entry.get('amount', {}).get('amount', 0))
            if amount < 0:
                continue

            remittance_info = entry.get('entryDetails', {}).get('transactionDetails', {}).get('remittanceInfo', {}).get('unstructured', '') or ''
            reference = entry.get('entryDetails', {}).get('transactionDetails', {}).get('reference', {}).get('endToEndId', '') or ''

            if any(term in remittance_info.lower() for term in excluded_terms_lower) or any(term in reference.lower() for term in excluded_terms_lower):
                continue

            # Check for duplicate by entryId
            existing = Transaction.query.filter_by(entryId=entryId).first()
            if existing:
                logger.debug(f'Transaction {entryId} already exists (by entryId), skipping')
                continue

            value_date = entry.get('valueDate', {}).get('Date', '')

            # Check for duplicates by amount + valueDate + account
            duplicate_by_data = Transaction.query.filter_by(
                account=account_number,
                amount=amount,
                valueDate=value_date
            ).first()

            if duplicate_by_data:
                logger.info(f'Duplicate transaction detected: Amount R{amount:.2f}, Date {value_date}, Account {account_number} - EntryId {entryId} differs from existing {duplicate_by_data.entryId}, skipping')
                continue

            txn = Transaction(
                entryId=entryId,
                account=account_number,
                amount=amount,
                remittance_info=remittance_info,
                reference=reference,
                valueDate=value_date,
                source='FNB-PAYMENT',
                timestamp=datetime.now(sast),
                posted='no',
                CID='unallocated',
                status='pending',
                original_reference=reference,
                original_remittance_info=remittance_info,
                original_CID='unallocated'
            )
            db.session.add(txn)
            new_count += 1
            logger.info(f'Adding transaction: {entryId} - R{amount:.2f} - {value_date}')

        except Exception as e:
            logger.error(f'Error processing entry: {e}')

    if new_count > 0:
        db.session.commit()
        logger.info(f'Committed {new_count} new transactions for {account_number}')

    return new_count

def main():
    with app.app_context():
        try:
            print("\n" + "="*80)
            print("ADDING MISSING TRANSACTIONS FROM LAST 15 DAYS")
            print("="*80 + "\n")

            # Show current DB stats
            sast = ZoneInfo('Africa/Johannesburg')
            now = datetime.now(sast)
            date_15_days_ago = (now - timedelta(days=15)).strftime('%Y-%m-%d')

            before_count = Transaction.query.filter(Transaction.valueDate >= date_15_days_ago).count()
            print(f"Transactions in DB before (last 15 days): {before_count}\n")

            token = get_access_token()
            accounts = [Config.FNB_ACCOUNT_NUMBER1, Config.FNB_ACCOUNT_NUMBER2]

            total_added = 0

            for account in accounts:
                print(f"\n--- Processing Account: {account} ---")
                entries = fetch_transactions_for_account(token, account, days_back=15)
                print(f"Total fetched from API: {len(entries)}")

                added = filter_and_store_transactions(entries, account)
                total_added += added
                print(f"Added to DB: {added}")

            # Show final stats
            after_count = Transaction.query.filter(Transaction.valueDate >= date_15_days_ago).count()

            print("\n" + "="*80)
            print(f"SUMMARY:")
            print(f"  Before: {before_count} transactions")
            print(f"  Added:  {total_added} transactions")
            print(f"  After:  {after_count} transactions")
            print("="*80 + "\n")

            if total_added != 51:
                print(f"⚠️  WARNING: Expected to add 51 transactions, but added {total_added}")
            else:
                print("✅ Successfully added all 51 missing transactions!")

        except Exception as e:
            logger.error(f'Failed to add transactions: {e}')
            print(f"\nERROR: {e}")
            print("\nTo restore from backup, run:")
            print("cp /srv/applications/fnb_EFT_payment_postings/data/fnb_transactions.db.backup_* /srv/applications/fnb_EFT_payment_postings/data/fnb_transactions.db")

if __name__ == '__main__':
    main()
