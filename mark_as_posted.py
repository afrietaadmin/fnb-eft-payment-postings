#!/usr/bin/env python3
"""
Script to mark all transactions (except failed ones) as posted
"""
from app import create_app, db
from app.models import Transaction, FailedTransaction, AuditLog
from datetime import datetime

def mark_transactions_as_posted():
    app = create_app()

    with app.app_context():
        # Get all entryIds from failed_transactions table (unresolved)
        failed_entry_ids = db.session.query(FailedTransaction.entryId)\
            .filter(FailedTransaction.resolved == False)\
            .all()

        failed_entry_ids = [entry[0] for entry in failed_entry_ids]

        print(f"Found {len(failed_entry_ids)} unresolved failed transactions")
        print(f"Failed entry IDs: {failed_entry_ids[:5]}..." if len(failed_entry_ids) > 5 else f"Failed entry IDs: {failed_entry_ids}")

        # Get all transactions that are NOT posted and NOT in failed list
        transactions_to_update = Transaction.query.filter(
            Transaction.posted == 'no',
            ~Transaction.entryId.in_(failed_entry_ids) if failed_entry_ids else True
        ).all()

        print(f"\nFound {len(transactions_to_update)} transactions to mark as posted")

        if len(transactions_to_update) == 0:
            print("No transactions to update!")
            return

        # Ask for confirmation
        total_amount = sum(t.amount for t in transactions_to_update)
        print(f"\nSummary:")
        print(f"  Transactions to mark as posted: {len(transactions_to_update)}")
        print(f"  Total amount: ZAR {total_amount:,.2f}")
        print(f"  Excluded (failed): {len(failed_entry_ids)}")

        confirm = input("\nProceed with marking these transactions as posted? (yes/no): ")

        if confirm.lower() not in ['yes', 'y']:
            print("Operation cancelled.")
            return

        # Update transactions
        current_time = datetime.utcnow()
        updated_count = 0

        for transaction in transactions_to_update:
            # Create audit log entry
            audit = AuditLog(
                entryId=transaction.entryId,
                action='marked_as_posted',
                field_name='posted',
                old_value='no',
                new_value='yes',
                changed_by='bulk_update_script'
            )
            db.session.add(audit)

            # Update transaction
            transaction.posted = 'yes'
            transaction.postedDate = current_time
            transaction.status = 'completed'
            transaction.updated_at = current_time

            updated_count += 1

            if updated_count % 50 == 0:
                print(f"  Updated {updated_count} transactions...")

        # Commit all changes
        db.session.commit()

        print(f"\n✅ Successfully marked {updated_count} transactions as posted!")
        print(f"Posted date set to: {current_time}")

        # Show final stats
        total_posted = Transaction.query.filter(Transaction.posted == 'yes').count()
        total_unposted = Transaction.query.filter(Transaction.posted == 'no').count()

        print(f"\nFinal Database Stats:")
        print(f"  Total posted: {total_posted}")
        print(f"  Total unposted: {total_unposted}")

if __name__ == '__main__':
    mark_transactions_as_posted()
