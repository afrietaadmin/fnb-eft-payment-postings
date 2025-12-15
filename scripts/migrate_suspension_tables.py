#!/usr/bin/env python3
"""
Migration script to create suspension-related database tables.
Run this script to initialize the new tables for the suspension feature.

Usage:
    python scripts/migrate_suspension_tables.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Customer, Service, Invoice, CachedPayment, Suspension, PaymentPattern
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate():
    """Create all new tables for suspension feature."""
    app = create_app()

    with app.app_context():
        try:
            logger.info("Starting suspension feature migration...")

            # Create all tables (existing tables won't be recreated)
            db.create_all()

            logger.info("✅ Successfully created/verified all tables:")
            logger.info("   - Customer")
            logger.info("   - Service")
            logger.info("   - Invoice")
            logger.info("   - CachedPayment")
            logger.info("   - Suspension")
            logger.info("   - PaymentPattern")

            logger.info("\nMigration complete!")
            logger.info("\nNext steps:")
            logger.info("1. Update your .env file with UISP API credentials if not already done")
            logger.info("2. Access the suspension feature at /suspensions")
            logger.info("3. Start by viewing suspension candidates")

            return True

        except Exception as e:
            logger.error(f"❌ Migration failed: {str(e)}")
            logger.exception(e)
            return False


if __name__ == '__main__':
    success = migrate()
    sys.exit(0 if success else 1)
