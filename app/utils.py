import logging
import sys
import os
import json
from functools import wraps
from datetime import datetime, timezone
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
    try:
        failed = FailedTransaction.query.filter_by(entryId=entryId).first()
        if failed:
            failed.resolved = True
            failed.manual_cid = manual_cid
            from datetime import datetime
            failed.resolved_at = datetime.utcnow()
            db.session.commit()

            txn = Transaction.query.filter_by(entryId=entryId).first()
            if txn and manual_cid:
                log_audit(entryId, 'CID_UPDATE', 'CID', txn.CID, manual_cid, 'web_ui')
                txn.CID = manual_cid
                txn.status = 'pending_repost'
                db.session.commit()
    except Exception as e:
        logging.error(f"Failed to resolve failed transaction: {e}")

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
