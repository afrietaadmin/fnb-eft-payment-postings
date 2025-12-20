import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

import requests
import json
import os
from app import create_app, db
from app.models import FailedTransaction, Transaction, ExecutionLog
from app.config import Config
from app.utils import setup_logging

logger = setup_logging('telegram_notifier')
app = create_app()

def send_telegram_message(message):
    """Send message without Markdown to avoid escaping issues"""
    try:
        payload = {'chat_id': Config.TELEGRAM_CHAT_ID, 'text': message}
        response = requests.post(Config.TELEGRAM_API_URL, json=payload)
        if response.status_code == 200:
            logger.info('Telegram message sent')
            return True
        else:
            logger.error(f'Telegram error {response.status_code}: {response.text}')
            return False
    except Exception as e:
        logger.error(f'Failed to send Telegram message: {e}')
        return False

def map_error_code(error_code, reason):
    """Map error codes to human-readable messages"""
    if error_code == '422':
        return '⚠️ Client is Archived - Cannot post to archived clients'
    elif error_code == 'DUPLICATE_UISP_MANUAL_REVIEW':
        return '⚠️ Duplicate Payment - Same amount already posted to this client'
    elif error_code == 'LEAD_CONVERSION_FAILED':
        return '❌ Lead Conversion Failed - Could not convert lead to client'
    else:
        return f'❌ Error ({error_code}): {reason[:80]}'

def build_summary():
    with app.app_context():
        summary = '📊 FNB EFT Payment Postings - Daily Summary\n\n'

        # Get latest post_payments_UISP execution log only
        latest_post = ExecutionLog.query.filter_by(script_name='post_payments_UISP')\
            .order_by(ExecutionLog.timestamp.desc()).first()

        if latest_post:
            summary += '════ PAYMENT POSTING RESULTS ════\n'
            if latest_post.status == 'SUCCESS':
                summary += f'✅ Status: Success\n'
                summary += f'📤 Posted: {latest_post.transactions_processed} transaction(s)\n'
                summary += f'💰 Total Amount: ZAR {latest_post.total_amount:,.2f}\n'

                if latest_post.transactions_failed > 0:
                    summary += f'❌ Failed: {latest_post.transactions_failed}\n'
            else:
                summary += f'❌ Status: Failed\n'
                summary += f'⚠️  Message: {latest_post.message}\n'

            summary += '\n'

        # Get unallocated transactions (missing CID)
        unallocated = Transaction.query.filter_by(CID='unallocated', posted='no').all()

        # Get actual failed transactions (posting errors)
        failed = FailedTransaction.query.filter_by(resolved=False).all()

        # Categorize failed transactions
        archived_clients = [f for f in failed if f.error_code == '422']
        duplicates = [f for f in failed if f.error_code == 'DUPLICATE_UISP_MANUAL_REVIEW']
        lead_conversions = [f for f in failed if f.error_code == 'LEAD_CONVERSION_FAILED']
        other_errors = [f for f in failed if f.error_code not in ['422', 'DUPLICATE_UISP_MANUAL_REVIEW', 'LEAD_CONVERSION_FAILED']]

        # Total items needing attention
        total_issues = len(unallocated) + len(failed)

        if total_issues == 0:
            summary += '✅ All transactions processed successfully!\n'
            summary += 'No unallocated or failed transactions.\n'
        else:
            summary += f'⚠️  ATTENTION REQUIRED: {total_issues} item(s) need action\n\n'

            # Section 1: Unallocated Transactions
            if unallocated:
                unallocated_amount = sum(t.amount for t in unallocated)
                summary += f'🔍 UNALLOCATED ({len(unallocated)} txn, ZAR {unallocated_amount:,.2f})\n'
                summary += '   Missing CID - Run sanitize_data to extract\n\n'

            # Section 2: Lead Conversions (if any)
            if lead_conversions:
                lead_amount = sum(Transaction.query.filter_by(entryId=f.entryId).first().amount
                                 for f in lead_conversions if Transaction.query.filter_by(entryId=f.entryId).first())
                summary += f'👤 LEAD CONVERSION FAILED ({len(lead_conversions)} txn, ZAR {lead_amount:,.2f})\n'
                for f in lead_conversions:
                    txn = Transaction.query.filter_by(entryId=f.entryId).first()
                    if txn:
                        summary += f'   • {f.entryId} (CID {txn.CID}): {f.reason[:60]}...\n'
                summary += '\n'

            # Section 3: Archived Clients
            if archived_clients:
                archived_amount = sum(Transaction.query.filter_by(entryId=f.entryId).first().amount
                                     for f in archived_clients if Transaction.query.filter_by(entryId=f.entryId).first())
                summary += f'🚫 ARCHIVED CLIENTS ({len(archived_clients)} txn, ZAR {archived_amount:,.2f})\n'
                summary += '   Need to be restored in UISP\n'
                for f in archived_clients:
                    txn = Transaction.query.filter_by(entryId=f.entryId).first()
                    if txn:
                        summary += f'   • {f.entryId} (CID {txn.CID}): ZAR {txn.amount:,.2f}\n'
                summary += '\n'

            # Section 4: Duplicate Payments
            if duplicates:
                dup_amount = sum(Transaction.query.filter_by(entryId=f.entryId).first().amount
                                for f in duplicates if Transaction.query.filter_by(entryId=f.entryId).first())
                summary += f'⚠️  DUPLICATES ({len(duplicates)} txn, ZAR {dup_amount:,.2f})\n'
                summary += '   Manual review required\n'
                for f in duplicates:
                    txn = Transaction.query.filter_by(entryId=f.entryId).first()
                    if txn:
                        summary += f'   • {f.entryId} (CID {txn.CID}): ZAR {txn.amount:,.2f}\n'
                summary += '\n'

            # Section 5: Other Errors
            if other_errors:
                other_amount = sum(Transaction.query.filter_by(entryId=f.entryId).first().amount
                                  for f in other_errors if Transaction.query.filter_by(entryId=f.entryId).first())
                summary += f'❌ OTHER ERRORS ({len(other_errors)} txn, ZAR {other_amount:,.2f})\n'
                for f in other_errors[:3]:  # Show first 3
                    txn = Transaction.query.filter_by(entryId=f.entryId).first()
                    if txn:
                        summary += f'   • {f.entryId} (CID {txn.CID})\n'
                        summary += f'     {map_error_code(f.error_code, f.reason)}\n'
                if len(other_errors) > 3:
                    summary += f'   ... and {len(other_errors) - 3} more errors\n'
                summary += '\n'

        # Web UI link
        summary += f'\n🔗 Web Dashboard: http://10.150.98.6:5000/failed\n'

        return summary

def main():
    try:
        summary = build_summary()
        print("=" * 60)
        print("TELEGRAM MESSAGE PREVIEW:")
        print("=" * 60)
        print(summary)
        print("=" * 60)

        success = send_telegram_message(summary)
        if success:
            logger.info('Telegram notification sent successfully')
        else:
            logger.error('Failed to send Telegram notification')
    except Exception as e:
        logger.error(f'Notifier failed: {e}')

if __name__ == '__main__':
    main()
