#!/usr/bin/env python3
"""
Update database to match UISP reality:
1. Mark 34 newly imported transactions as posted='yes' (already in UISP)
2. Update their CID to match UISP client_id
3. Add 3 manually posted transactions not in DB
4. Flag amount mismatches for review
"""
import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from app import create_app, db
from app.models import Transaction, FailedTransaction, AuditLog
from app.config import Config
from app.utils import setup_logging, log_audit

logger = setup_logging('update_db_from_uisp_cross_check')
app = create_app()

def fetch_uisp_payments(from_date, to_date):
    """Fetch all payments from UISP API"""
    try:
        url = f"{Config.UISP_BASE_URL}payments"
        headers = {
            Config.UISP_AUTHORIZATION: Config.UISP_API_KEY
        }
        params = {
            'createdDateFrom': from_date,
            'createdDateTo': to_date,
            'limit': 10000
        }
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f'Failed to fetch UISP payments: {e}')
        return []

def main():
    with app.app_context():
        try:
            from_date = '2025-12-18'
            to_date = '2026-01-06'

            print("\n" + "="*120)
            print("UPDATE DATABASE FROM UISP CROSS-CHECK")
            print("="*120)

            # Fetch UISP payments
            uisp_payments = fetch_uisp_payments(from_date, to_date)
            uisp_by_provider_id = {p.get('providerPaymentId'): p for p in uisp_payments if p.get('providerPaymentId')}

            logger.info(f'Fetched {len(uisp_payments)} payments from UISP')

            # Get DB transactions
            db_txns = Transaction.query.filter(
                Transaction.valueDate >= from_date,
                Transaction.valueDate <= to_date
            ).all()

            # Find 34 newly imported that are already in UISP
            already_in_uisp = []
            for txn in db_txns:
                if txn.CID == 'unallocated' and txn.posted == 'no':
                    if txn.entryId in uisp_by_provider_id:
                        already_in_uisp.append(txn)

            print(f"\n📋 Found {len(already_in_uisp)} newly imported transactions already in UISP")
            print("-" * 120)

            # Update these transactions
            sast = ZoneInfo('Africa/Johannesburg')
            updated = 0
            updated_cids = {}

            for txn in already_in_uisp:
                uisp_payment = uisp_by_provider_id[txn.entryId]
                old_cid = txn.CID
                new_cid = str(uisp_payment.get('clientId', 'unallocated'))
                uisp_payment_id = str(uisp_payment.get('id'))

                # Update transaction
                txn.posted = 'yes'
                txn.CID = new_cid
                txn.UISPpaymentId = uisp_payment_id
                txn.postedDate = datetime.now(sast)
                txn.status = 'posted'

                # Log the audit
                log_audit(
                    txn.entryId,
                    'UPDATE_FROM_UISP_SYNC',
                    f'CID: {old_cid} -> {new_cid}; posted: no -> yes',
                    f'CID: {new_cid}; posted: yes',
                    'system'
                )

                updated += 1
                updated_cids[txn.entryId] = new_cid

                if updated <= 5:
                    print(f"  {txn.entryId:20} | CID: {old_cid:12} → {new_cid:6} | Amount: R{txn.amount:10,.2f}")

            if updated > 5:
                print(f"  ... and {updated - 5} more")

            # Commit changes
            if updated > 0:
                db.session.commit()
                logger.info(f'✅ Updated {updated} transactions as posted to UISP')
                print(f"\n✅ Updated {updated} transactions in database")

            # Find 3 manually posted not in DB
            manually_posted = []
            for payment in uisp_payments:
                provider_id = payment.get('providerPaymentId')
                if not provider_id:
                    continue

                # Check if exists in DB
                exists = Transaction.query.filter_by(entryId=provider_id).first()
                if not exists:
                    manually_posted.append(payment)

            print(f"\n📋 Found {len(manually_posted)} manually posted in UISP not in local DB")
            print("-" * 120)

            # Add them to DB
            added = 0
            for payment in manually_posted:
                try:
                    provider_id = payment.get('providerPaymentId')
                    client_id = payment.get('clientId')
                    amount = float(payment.get('amount', 0))
                    created_date = payment.get('createdDate', '').split('T')[0] if payment.get('createdDate') else ''
                    note = payment.get('note', '')

                    # Try to extract account from note or reference
                    account = Config.FNB_ACCOUNT_NUMBER2 or Config.FNB_ACCOUNT_NUMBER1  # Default to main account

                    # Create transaction record
                    txn = Transaction(
                        entryId=provider_id,
                        account=account,
                        amount=amount,
                        valueDate=created_date,
                        CID=str(client_id) if client_id else 'unallocated',
                        posted='yes',
                        UISPpaymentId=str(payment.get('id')),
                        postedDate=datetime.fromisoformat(payment.get('createdDate').replace('Z', '+00:00')) if payment.get('createdDate') else datetime.now(sast),
                        status='posted',
                        source='UISP-SYNC',
                        note=f'Manually posted via UISP. {note}',
                        timestamp=datetime.now(sast),
                        reference=provider_id,
                        remittance_info=note or ''
                    )

                    db.session.add(txn)
                    added += 1

                    if added <= 3:
                        print(f"  {provider_id:20} | CID: {client_id:6} | Amount: R{amount:10,.2f} | Date: {created_date}")

                except Exception as e:
                    logger.error(f'Error adding transaction {payment.get("providerPaymentId")}: {e}')

            if added > 0:
                db.session.commit()
                logger.info(f'✅ Added {added} manually posted transactions to database')
                print(f"\n✅ Added {added} manually posted transactions to database")

            # Check for amount mismatches
            amount_mismatches = []
            for txn in db_txns:
                if txn.entryId in uisp_by_provider_id:
                    uisp_payment = uisp_by_provider_id[txn.entryId]
                    uisp_amount = float(uisp_payment.get('amount', 0))
                    if abs(txn.amount - uisp_amount) > 0.01:  # More than 1 cent difference
                        amount_mismatches.append({
                            'entryId': txn.entryId,
                            'db_amount': txn.amount,
                            'uisp_amount': uisp_amount,
                            'difference': uisp_amount - txn.amount,
                            'cid': txn.CID
                        })

            if amount_mismatches:
                print(f"\n⚠️  Found {len(amount_mismatches)} amount mismatches between DB and UISP")
                print("-" * 120)
                print("These may indicate partial payments, corrections, or data entry errors:")
                print(f"{'EntryId':<20} {'DB Amount':>12} {'UISP Amount':>12} {'Difference':>12} {'CID':>6}")
                print("-" * 80)
                for m in amount_mismatches[:10]:
                    print(f"{m['entryId']:<20} R{m['db_amount']:>11,.2f} R{m['uisp_amount']:>11,.2f} R{m['difference']:>11,.2f} {m['cid']:>6}")
                if len(amount_mismatches) > 10:
                    print(f"... and {len(amount_mismatches) - 10} more")

            # Summary
            print(f"\n{'='*120}")
            print("SUMMARY")
            print(f"{'='*120}")
            print(f"✅ Updated:      {updated} transactions marked as posted")
            print(f"✅ Added:        {added} manually posted transactions")
            print(f"⚠️  Mismatches:  {len(amount_mismatches)} amount discrepancies")

            print(f"\n{'='*120}\n")

            logger.info(f'✅ Database update complete: {updated} updated, {added} added')

        except Exception as e:
            logger.error(f'✗ Update failed: {e}')
            raise

if __name__ == '__main__':
    main()
