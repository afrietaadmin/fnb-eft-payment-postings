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

def build_summary():
    with app.app_context():
        summary = '📊 FNB EFT Payment Postings Summary\n\n'

        # Get latest execution logs
        logs = ExecutionLog.query.order_by(ExecutionLog.timestamp.desc()).limit(5).all()
        summary += '══ Recent Executions ══\n'
        for log in logs:
            status_emoji = '✅' if log.status == 'SUCCESS' else '❌'
            summary += f'{status_emoji} {log.script_name}: {log.transactions_processed} processed'
            if log.transactions_failed > 0:
                summary += f', {log.transactions_failed} failed'
            if log.total_amount > 0:
                summary += f', ZAR {log.total_amount:,.2f}'
            summary += '\n'

        # Get unallocated transactions (missing CID)
        unallocated = Transaction.query.filter_by(CID='unallocated', posted='no').all()

        # Get actual failed transactions (posting errors)
        failed = FailedTransaction.query.filter_by(resolved=False).all()

        # Total items needing attention
        total_issues = len(unallocated) + len(failed)

        summary += f'\n══ Total Items Needing Attention: {total_issues} ══\n'

        # Section 1: Unallocated Transactions
        if unallocated:
            summary += f'\n⚠️  UNALLOCATED TRANSACTIONS (Missing CID)\n'
            summary += f'🔍 {len(unallocated)} transaction(s) need CID assignment\n\n'

            for txn in unallocated[:5]:  # Show first 5
                summary += f'  • {txn.entryId} - ZAR {txn.amount:,.2f}\n'

                # Add reference field (truncate if too long)
                ref = txn.reference or 'N/A'
                if len(ref) > 40:
                    ref = ref[:37] + '...'
                summary += f'    Ref: "{ref}"\n'

                # Add remittance info (truncate if too long)
                info = txn.remittance_info or 'N/A'
                if len(info) > 50:
                    info = info[:47] + '...'
                summary += f'    Info: "{info}"\n'
                summary += f'    Date: {txn.valueDate}\n\n'

            if len(unallocated) > 5:
                summary += f'  ... and {len(unallocated) - 5} more unallocated transactions\n'

        # Section 2: Failed Transactions (API errors, duplicates, etc.)
        if failed:
            summary += f'\n🚨 FAILED POSTINGS (API Errors/Duplicates)\n'
            summary += f'❌ {len(failed)} transaction(s) failed during posting\n\n'

            for f in failed[:5]:  # Show first 5
                txn = Transaction.query.filter_by(entryId=f.entryId).first()
                if txn:
                    summary += f'  • {f.entryId} - ZAR {txn.amount:,.2f}\n'
                    summary += f'    CID: {txn.CID}\n'

                    # Add failure reason (truncate if too long)
                    reason = f.reason or 'Unknown error'
                    if len(reason) > 60:
                        reason = reason[:57] + '...'
                    summary += f'    Error: {reason}\n'

                    # Add reference for context
                    ref = txn.reference or 'N/A'
                    if len(ref) > 40:
                        ref = ref[:37] + '...'
                    summary += f'    Ref: "{ref}"\n'
                    summary += f'    Date: {txn.valueDate}\n\n'

            if len(failed) > 5:
                summary += f'  ... and {len(failed) - 5} more failed transactions\n'

        # If nothing needs attention
        if total_issues == 0:
            summary += '\n✅ All transactions processed successfully!\n'
            summary += 'No unallocated or failed transactions.\n'

        # Web UI link
        summary += f'\n📱 Access Web UI:\nhttp://10.150.98.6:5000/failed\n'

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
