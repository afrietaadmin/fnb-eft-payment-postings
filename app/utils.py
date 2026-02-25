import logging
import sys
import os
import json
import re
import requests
from functools import wraps
from datetime import datetime, timezone, timedelta
from flask import request
from flask_login import current_user
from app.config import Config
from app.models import ExecutionLog, AuditLog, FailedTransaction, Transaction, UserActivityLog
from app import db

def setup_logging(script_name):
    os.makedirs(os.path.dirname(Config.LOG_FILE), exist_ok=True)
    logger = logging.getLogger(script_name)
    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(Config.LOG_FILE)
    console_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

def log_user_activity(action_type, action_description=None):
    """Decorator to log user activities"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                # Execute the original function
                result = f(*args, **kwargs)

                # Log the activity after successful execution
                if current_user.is_authenticated:
                    log = UserActivityLog(
                        user_id=current_user.id,
                        username=current_user.username,
                        action_type=action_type,
                        action_description=action_description,
                        ip_address=request.remote_addr,
                        user_agent=request.user_agent.string[:500] if request.user_agent else None,
                        endpoint=request.endpoint,
                        method=request.method,
                        timestamp=datetime.now(timezone.utc)
                    )
                    db.session.add(log)
                    db.session.commit()
            except Exception as e:
                # Log error but don't fail the request
                logging.error(f"Failed to log user activity: {e}")
                try:
                    db.session.rollback()
                except:
                    pass

            return result
        return decorated_function
    return decorator

def log_execution(script_name, status, message, transactions_processed=0, transactions_failed=0, total_amount=0.0):
    try:
        log = ExecutionLog(
            script_name=script_name,
            status=status,
            message=message,
            transactions_processed=transactions_processed,
            transactions_failed=transactions_failed,
            total_amount=total_amount
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        logging.error(f"Failed to log execution: {e}")

def log_audit(entryId, action, field_name=None, old_value=None, new_value=None, changed_by='system'):
    try:
        audit = AuditLog(
            entryId=entryId,
            action=action,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by
        )
        db.session.add(audit)
        db.session.commit()
    except Exception as e:
        logging.error(f"Failed to log audit: {e}")

def add_failed_transaction(entryId, reason, error_code=None):
    try:
        failed = FailedTransaction.query.filter_by(entryId=entryId, resolved=False).first()
        if not failed:
            failed = FailedTransaction(
                entryId=entryId,
                reason=reason,
                error_code=error_code
            )
            db.session.add(failed)
        else:
            failed.reason = reason
            failed.error_code = error_code
        db.session.commit()
        return failed
    except Exception as e:
        logging.error(f"Failed to add failed transaction: {e}")

def resolve_failed_transaction(entryId, manual_cid=None):
    import re
    try:
        failed = FailedTransaction.query.filter_by(entryId=entryId).first()
        if failed:
            failed.resolved = True
            failed.manual_cid = manual_cid
            from datetime import datetime
            failed.resolved_at = datetime.utcnow()
            db.session.commit()

            # Handle multiple transactions with same entryId (cross-account duplicates)
            all_txns = Transaction.query.filter_by(entryId=entryId).all()
            txn = None
            if len(all_txns) > 1:
                # Multiple transactions - prefer the one with unallocated CID
                txn = next((t for t in all_txns if t.CID == 'unallocated'), all_txns[0])
            else:
                txn = all_txns[0] if all_txns else None

            if txn and manual_cid:
                # Extract numeric portion from CID (handle both "123" and "CID123" formats)
                cid_match = re.search(r'\d+', str(manual_cid).strip())
                if cid_match:
                    extracted_cid = cid_match.group()
                    log_audit(entryId, 'CID_UPDATE', 'CID', txn.CID, extracted_cid, 'web_ui')
                    txn.CID = extracted_cid
                    txn.status = 'pending_repost'
                    db.session.commit()
    except Exception as e:
        logging.error(f"Failed to resolve failed transaction: {e}")

def fetch_fnb_transactions_by_period(from_date, to_date, cid=None, search_text=None):
    """
    Fetch FNB transactions for a given date range from both accounts,
    optionally filtering by CID and/or search text.
    Returns a list of raw FNB API entry dicts with 'account_number' added.
    Raises ValueError for invalid date range, Exception for API errors.
    """
    # Validate dates
    try:
        dt_from = datetime.strptime(from_date, '%Y-%m-%d')
        dt_to = datetime.strptime(to_date, '%Y-%m-%d')
    except ValueError:
        raise ValueError(f"Invalid date format. Use YYYY-MM-DD.")

    if dt_from > dt_to:
        raise ValueError("from_date must be before to_date.")

    if (dt_to - dt_from).days > Config.MAX_API_QUERY_DAYS:
        raise ValueError(f"Date range cannot exceed {Config.MAX_API_QUERY_DAYS} days.")

    # Authenticate with FNB
    auth_response = requests.post(
        Config.FNB_AUTH_URL,
        data={'grant_type': 'client_credentials'},
        auth=(Config.FNB_CLIENT_ID, Config.FNB_CLIENT_SECRET),
        timeout=10
    )
    auth_response.raise_for_status()
    access_token = auth_response.json()['access_token']

    headers = {
        'Authorization': f'Bearer {access_token}',
        'X-Request-ID': f"req-{datetime.now().strftime('%H%M%S')}"
    }

    cid_upper = cid.upper() if cid else None
    search_upper = search_text.upper() if search_text else None

    all_matched = []

    for account_number in [Config.FNB_ACCOUNT_NUMBER1, Config.FNB_ACCOUNT_NUMBER2]:
        if not account_number:
            continue

        url = Config.FNB_BASE_URL + Config.FNB_TRANSACTION_HISTORY_URL.format(accountNumber=account_number)
        params = {'fromDate': from_date, 'toDate': to_date}
        page = 1

        while True:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            for entry in data.get('entry', []):
                txn_details = entry.get('entryDetails', {}).get('transactionDetails', {})
                remittance = (txn_details.get('remittanceInfo', {}).get('unstructured', '') or '').upper()
                reference = (txn_details.get('reference', {}).get('endToEndId', '') or '').upper()
                combined = remittance + ' ' + reference

                # Filter by CID
                if cid_upper and f'CID{cid_upper}' not in combined and cid_upper not in combined:
                    continue

                # Filter by search text
                if search_upper and search_upper not in combined:
                    continue

                entry['account_number'] = account_number
                all_matched.append(entry)

            pagination = data.get('groupHeader', {}).get('pagination', {})
            if pagination.get('lastPageIndicator', True):
                break
            last_item_key = pagination.get('lastItemKey')
            if not last_item_key:
                break
            params['lastItemKey'] = last_item_key
            page += 1

    return all_matched


def get_suggested_cid(txn):
    """
    Suggest a CID for a transaction using:
    1. CID pattern in reference field
    2. CID pattern in remittance_info field
    3. UISP EFT payment reference mapping
    Returns numeric CID string, or None.
    """
    reference = (txn.reference or '').upper()
    remittance = (txn.remittance_info or '').upper()

    # Method 1 & 2: Parse "CID<digits>" from reference or remittance_info
    for text in [reference, remittance]:
        if 'CID' in text:
            parts = text.split('CID')
            if len(parts) > 1:
                numeric = re.match(r'\d+', parts[1].strip())
                if numeric:
                    return numeric.group()

    # Method 3: Match against UISP EFT reference mappings
    try:
        url = f"{Config.UISP_BASE_URL}clients"
        headers = {
            'Content-Type': 'application/json',
            Config.UISP_AUTHORIZATION: Config.UISP_API_KEY
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            for client in resp.json():
                client_id = client.get('id')
                for attr in client.get('attributes', []):
                    if attr.get('key') == 'eftPaymentReferenceUsed':
                        eft_ref = (attr.get('value') or '').upper()
                        if eft_ref and (eft_ref in reference or eft_ref in remittance):
                            return str(client_id)
    except Exception:
        pass

    return None


def update_telegram_messages(section, message):
    os.makedirs(os.path.dirname(Config.TELEGRAM_MESSAGES_FILE), exist_ok=True)
    try:
        if os.path.exists(Config.TELEGRAM_MESSAGES_FILE):
            with open(Config.TELEGRAM_MESSAGES_FILE, 'r') as f:
                data = json.load(f)
        else:
            data = {}

        data[section] = message

        with open(Config.TELEGRAM_MESSAGES_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to update telegram messages: {e}")
