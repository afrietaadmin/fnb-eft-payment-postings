#!/usr/bin/env python3
"""
Create initial users for the authentication system
"""

import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

from datetime import datetime, timezone
from app import create_app, db
from app.models import User
from app.auth import hash_password
from app.utils import setup_logging

logger = setup_logging('create_initial_users')
app = create_app()

def main():
    with app.app_context():
        try:
            print("\n" + "="*80)
            print("CREATING INITIAL USERS FOR FNB PAYMENT SYSTEM")
            print("="*80 + "\n")

            # Pre-generated passwords for initial users
            users_to_create = [
                {
                    'username': 'Shahin-Admin',
                    'password': 'RhijWM8ilF2^',
                    'full_name': 'Shahin - Administrator',
                    'role': 'admin'
                },
                {
                    'username': 'Anthonia',
                    'password': 'ev!rbBeDea74',
                    'full_name': 'Anthonia',
                    'role': 'user'
                },
                {
                    'username': 'Omolara',
                    'password': 'PZyObE1TWhFc',
                    'full_name': 'Omolara',
                    'role': 'user'
                },
                {
                    'username': 'Kuban',
                    'password': '&PwJkE@56xe3',
                    'full_name': 'Kuban',
                    'role': 'user'
                }
            ]

            created_count = 0
            skipped_count = 0

            print("Creating users...\n")

            for user_info in users_to_create:
                # Check if user already exists
                existing_user = User.query.filter_by(username=user_info['username']).first()

                if existing_user:
                    print(f"⏭️  {user_info['username']:15} - Already exists (skipping)")
                    skipped_count += 1
                    continue

                # Hash password
                password_hash = hash_password(user_info['password'])

                # Create user
                user = User(
                    username=user_info['username'],
                    password_hash=password_hash,
                    full_name=user_info['full_name'],
                    role=user_info['role'],
                    is_active=True,
                    must_change_password=True,
                    created_by='system',
                    created_at=datetime.now(timezone.utc)
                )
                db.session.add(user)
                created_count += 1

                role_display = f"[{user_info['role'].upper()}]"
                print(f"✅ {user_info['username']:15} - Created {role_display}")

            db.session.commit()

            print("\n" + "="*80)
            print("SUMMARY")
            print("="*80)
            print(f"  Created:  {created_count} users")
            print(f"  Skipped:  {skipped_count} users (already exist)")
            print(f"  Total:    {created_count + skipped_count} users configured")
            print("="*80)

            if created_count > 0:
                print("\n" + "⚠️  INITIAL CREDENTIALS " + "="*60)
                print("IMPORTANT: Each user must change their password on first login")
                print("="*80 + "\n")

                for user_info in users_to_create:
                    user = User.query.filter_by(username=user_info['username']).first()
                    if user:
                        print(f"Username: {user_info['username']}")
                        print(f"Password: {user_info['password']}")
                        print(f"Role:     {user_info['role'].upper()}")
                        print(f"First Login: Must change password immediately")
                        print()

                print("="*80)
                print("Save these credentials securely!")
                print("="*80 + "\n")

            logger.info(f'Created {created_count} initial users')

        except Exception as e:
            logger.error(f'Failed to create users: {e}')
            print(f"\n❌ ERROR: {e}")
            db.session.rollback()
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    main()
