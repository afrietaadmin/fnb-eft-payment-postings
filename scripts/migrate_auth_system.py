#!/usr/bin/env python3
"""
Database migration script for authentication system
Creates User and UserActivityLog tables
"""

import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from app import create_app, db
from app.models import User, UserActivityLog
from app.utils import setup_logging

logger = setup_logging('migrate_auth_system')
app = create_app()

def main():
    with app.app_context():
        try:
            print("\n" + "="*80)
            print("AUTHENTICATION SYSTEM DATABASE MIGRATION")
            print("="*80 + "\n")

            # Create tables
            print("Creating tables...")
            db.create_all()

            # Verify tables exist
            inspector = db.inspect(db.engine)
            existing_tables = inspector.get_table_names()

            print(f"\nExisting tables in database: {len(existing_tables)}")

            if 'users' in existing_tables:
                print("✅ users table created")
                user_columns = [col['name'] for col in inspector.get_columns('users')]
                print(f"   Columns: {', '.join(user_columns)}")
            else:
                print("❌ users table NOT found")

            if 'user_activity_logs' in existing_tables:
                print("✅ user_activity_logs table created")
                log_columns = [col['name'] for col in inspector.get_columns('user_activity_logs')]
                print(f"   Columns: {', '.join(log_columns)}")
            else:
                print("❌ user_activity_logs table NOT found")

            print("\n" + "="*80)
            print("MIGRATION COMPLETE")
            print("="*80)
            print("\nNext steps:")
            print("1. Run scripts/create_initial_users.py to create the 4 initial users")
            print("2. Update app/__init__.py with Flask-Login configuration")
            print("3. Create authentication routes and templates")
            print("="*80 + "\n")

            logger.info('Database migration completed successfully')

        except Exception as e:
            logger.error(f'Migration failed: {e}')
            print(f"\n❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    main()
