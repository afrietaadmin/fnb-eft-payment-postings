import sys
import os
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app import create_app, db
from app.models import Transaction
from app.config import Config
from app.utils import setup_logging, log_execution, log_audit, update_telegram_messages

logger = setup_logging('fetch_fnb_transactions')
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

def fetch_transactions_for_account(access_token, account_number):
    sast = ZoneInfo('Africa/Johannesburg')
    now = datetime.now(sast)
    to_date = now.strftime('%Y-%m-%d')
    from_date = (now - timedelta(days=Config.FETCH_DAYS_BACK)).strftime('%Y-%m-%d')

    headers = {
        'Authorization': f'Bearer {access_token}',
        'X-Request-ID': f"req-{datetime.now().strftime('%H%M%S')}"
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

            # Check for duplicate by entryId + account (entry IDs can repeat across accounts)
            existing = Transaction.query.filter_by(entryId=entryId, account=account_number).first()
            if existing:
                logger.debug(f'Transaction {entryId} already exists in account {account_number}, skipping')
                continue

            value_date = entry.get('valueDate', {}).get('Date', '')

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
                # Store original data from FNB
                original_reference=reference,
                original_remittance_info=remittance_info,
                original_CID='unallocated'
            )
            db.session.add(txn)
            new_count += 1

        except Exception as e:
            logger.error(f'Error processing entry: {e}')

    if new_count > 0:
        db.session.commit()
        logger.info(f'Added {new_count} new transactions for {account_number}')

    return new_count

def main():
    with app.app_context():
        try:
            token = get_access_token()
            accounts = [Config.FNB_ACCOUNT_NUMBER1, Config.FNB_ACCOUNT_NUMBER2]
            total_new = 0

            for account in accounts:
                entries = fetch_transactions_for_account(token, account)
                new = filter_and_store_transactions(entries, account)
                total_new += new

            logger.info(f'Fetch complete: {total_new} new transactions')
            update_telegram_messages('fetch_fnb_transactions', f'Fetched {total_new} new transactions')
            log_execution('fetch_fnb_transactions', 'SUCCESS', f'Fetched {total_new} transactions', transactions_processed=total_new)

        except Exception as e:
            logger.error(f'Fetch failed: {e}')
            log_execution('fetch_fnb_transactions', 'FAILED', str(e))
            update_telegram_messages('fetch_fnb_transactions', f'Error: {e}')

if __name__ == '__main__':
    main()
