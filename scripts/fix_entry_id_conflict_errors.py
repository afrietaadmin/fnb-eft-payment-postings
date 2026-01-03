#!/usr/bin/env python3
"""
Migration script to remove BUG_ENTRY_ID_CONFLICT errors from failed_transactions.

CONTEXT:
- Entry IDs can legitimately exist in multiple accounts (different FNB accounts)
- The database schema supports this with composite uniqueness (entryId, account)
- Previous validation incorrectly blocked these cross-account transactions
- This script removes those blocks so transactions can be posted

AFFECTED:
- 41 transactions were blocked with BUG_ENTRY_ID_CONFLICT error
- All have valid CIDs and can be posted to their respective accounts
- Many were already manually marked as posted in web GUI

SAFETY:
- Transactions marked as posted (posted='yes') won't be re-posted
- Only transactions with posted='no' and valid CID will be posted
- No duplicate posting will occur
"""

import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from app import create_app, db
from app.models import FailedTransaction
from app.utils import setup_logging

logger = setup_logging('fix_entry_id_conflict_errors')
app = create_app()

def main():
    with app.app_context():
        try:
            # Find all BUG_ENTRY_ID_CONFLICT errors
            conflicts = FailedTransaction.query.filter_by(
                error_code='BUG_ENTRY_ID_CONFLICT'
            ).all()

            if not conflicts:
                logger.info('No BUG_ENTRY_ID_CONFLICT errors found - nothing to fix')
                return

            count = len(conflicts)
            entry_ids = [f.entryId for f in conflicts]

            logger.info(f'Found {count} transactions blocked with BUG_ENTRY_ID_CONFLICT')
            logger.info(f'Entry IDs: {entry_ids}')

            # Remove the error records
            for conflict in conflicts:
                logger.info(f'Removing block for entry ID {conflict.entryId}')
                db.session.delete(conflict)

            db.session.commit()

            logger.info(f'✅ Successfully removed {count} BUG_ENTRY_ID_CONFLICT blocks')
            logger.info('Transactions can now be posted to their respective accounts')

        except Exception as e:
            logger.error(f'❌ Failed to apply fix: {e}')
            db.session.rollback()
            raise

if __name__ == '__main__':
    main()
