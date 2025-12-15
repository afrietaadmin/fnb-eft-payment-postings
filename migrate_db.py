#!/usr/bin/env python3
"""
Database migration script to add new columns and tables
"""
import sqlite3
from app import create_app, db
from app.models import Transaction, UISPPayment

def migrate_database():
    app = create_app()

    with app.app_context():
        print("Starting database migration...")

        # Get the database path
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        print(f"Database: {db_path}")

        # Connect directly to SQLite
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Add new columns to transactions table
        try:
            print("\n1. Adding original_reference column...")
            cursor.execute("ALTER TABLE transactions ADD COLUMN original_reference TEXT")
            print("   ✅ Added original_reference")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("   ⏭️  Column already exists")
            else:
                raise

        try:
            print("\n2. Adding original_remittance_info column...")
            cursor.execute("ALTER TABLE transactions ADD COLUMN original_remittance_info TEXT")
            print("   ✅ Added original_remittance_info")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("   ⏭️  Column already exists")
            else:
                raise

        try:
            print("\n3. Adding original_CID column...")
            cursor.execute("ALTER TABLE transactions ADD COLUMN original_CID VARCHAR(50)")
            print("   ✅ Added original_CID")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("   ⏭️  Column already exists")
            else:
                raise

        conn.commit()

        # Backfill original data for existing transactions
        print("\n4. Backfilling original data for existing transactions...")
        cursor.execute("""
            UPDATE transactions
            SET original_reference = reference,
                original_remittance_info = remittance_info,
                original_CID = CID
            WHERE original_reference IS NULL
        """)
        updated = cursor.rowcount
        conn.commit()
        print(f"   ✅ Backfilled {updated} transactions")

        conn.close()

        # Create new UISPPayment table using SQLAlchemy
        print("\n5. Creating UISP payments table...")
        db.create_all()
        print("   ✅ Created uisp_payments table")

        # Verify the changes
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(transactions)")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"\n✅ Transaction table columns: {len(columns)}")
        print(f"   New columns present: original_reference={('original_reference' in columns)}, "
              f"original_remittance_info={('original_remittance_info' in columns)}, "
              f"original_CID={('original_CID' in columns)}")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in cursor.fetchall()]
        print(f"\n✅ Database tables: {', '.join(tables)}")

        conn.close()

        print("\n🎉 Migration completed successfully!")

if __name__ == '__main__':
    migrate_database()
