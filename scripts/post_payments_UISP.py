import sys
sys.path.insert(0, '/srv/applications/fnb_EFT_payment_postings')

import json
import csv
import os
import requests
from datetime import datetime, timezone, timedelta
from app import create_app, db
from app.models import Transaction, FailedTransaction
from app.config import Config
from app.utils import setup_logging, log_execution, log_audit, update_telegram_messages

logger = setup_logging('post_payments_UISP')
app = create_app()

DUMP_DIR = os.path.join(Config.BASE_PATH, 'uisp_requests')
os.makedirs(DUMP_DIR, exist_ok=True)

def build_uisp_payload(txn):
    """Build UISP payment payload without posting"""
    if not txn.CID or txn.CID == 'unallocated':
        return None

    try:
        uisp_cid = int(txn.CID.strip())
        amount = float(txn.amount)
        entryId = txn.entryId

        formatted_note = f"{txn.note or ''} | TXN: {entryId}".strip(' |')
        provider_payment_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S%z')

        payload = {
            'clientId': uisp_cid,
            'methodId': 'd8c1eae9-d41d-479f-aeaf-38497975d7b3',
            'currencyCode': 'ZAR',
            'applyToInvoicesAutomatically': True,
            'providerPaymentId': entryId,
            'providerPaymentTime': provider_payment_time,
            'providerName': 'FNB-EFT',
            'amount': amount,
            'userId': 1000,
            'note': formatted_note
        }
        return payload
    except Exception as e:
        logger.error(f'Error building payload for {txn.entryId}: {e}')
        return None

def dump_uisp_requests(transactions):
    """Dump UISP payloads to JSON file with timestamp"""
    if not transactions:
        return None

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(DUMP_DIR, f'uisp_requests_{timestamp}.json')

    payloads = []
    for txn in transactions:
        payload = build_uisp_payload(txn)
        if payload:
            payloads.append({
                'entryId': txn.entryId,
                'amount': txn.amount,
                'account': txn.account,
                'reference': txn.reference,
                'remittance_info': txn.remittance_info,
                'uisp_payload': payload
            })

    output = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_requests': len(payloads),
        'total_amount': sum(p['amount'] for p in payloads),
        'requests': payloads
    }

    try:
        with open(filename, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        logger.info(f'Dumped {len(payloads)} UISP request payloads to {filename}')
        return filename
    except Exception as e:
        logger.error(f'Failed to dump requests: {e}')
        return None

def dump_uisp_requests_csv(transactions):
    """Dump UISP payloads to CSV file with timestamp"""
    if not transactions:
        return None

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(DUMP_DIR, f'uisp_requests_{timestamp}.csv')

    try:
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Entry ID', 'CID', 'Amount', 'Currency', 'Account',
                'Reference', 'Remittance Info', 'Note', 'Value Date',
                'Provider Payment Time', 'Auto Apply'
            ])

            for txn in transactions:
                payload = build_uisp_payload(txn)
                if payload:
                    writer.writerow([
                        txn.entryId,
                        txn.CID,
                        txn.amount,
                        'ZAR',
                        txn.account,
                        txn.reference or '',
                        txn.remittance_info or '',
                        txn.note or '',
                        txn.valueDate or '',
                        payload['providerPaymentTime'],
                        'Yes'
                    ])

        logger.info(f'Dumped {len(transactions)} UISP requests to CSV: {filename}')
        return filename
    except Exception as e:
        logger.error(f'Failed to dump CSV: {e}')
        return None

def check_duplicate_payment(txn):
    """
    Check if this CID already has a posted payment with same amount in UISP within last 15 days.
    Returns dict with duplicate info if found, None otherwise.
    """
    if not txn.CID or txn.CID == 'unallocated':
        return None

    try:
        UISP_DUPLICATE_DAYS = 15  # Always check last 15 days in UISP

        today = datetime.now(timezone.utc)
        cutoff = today - timedelta(days=UISP_DUPLICATE_DAYS)
        date_from = cutoff.strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')

        # Query UISP for payments for this CID
        base_url = Config.UISP_BASE_URL.replace('/v2.0/', '/v1.0/')
        url = f"{base_url}payments?createdDateFrom={date_from}&createdDateTo={date_to}&clientId={txn.CID}"

        headers = {
            Config.UISP_AUTHORIZATION: Config.UISP_API_KEY,
            'Content-Type': 'application/json'
        }

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            payments = response.json()

            # Check for matching amount (same CID + same amount)
            for payment in payments:
                payment_amount = float(payment.get('amount', 0))
                if payment_amount == float(txn.amount):
                    # Found duplicate with same amount
                    created_date = datetime.fromisoformat(payment['createdDate'].replace('Z', '+00:00'))
                    days_ago = (datetime.now(timezone.utc) - created_date).days

                    return {
                        'source': 'UISP',
                        'amount': payment_amount,
                        'created_date': created_date,
                        'days_ago': days_ago,
                        'provider': payment.get('providerName', 'Unknown'),
                        'provider_id': payment.get('providerPaymentId', 'N/A'),
                        'method': payment.get('method', {}).get('name', 'Unknown'),
                        'uisp_payment_id': payment.get('id')
                    }

            return None  # No matching amount found
        else:
            logger.warning(f'UISP API returned {response.status_code} for CID {txn.CID}')
            return None

    except Exception as e:
        logger.error(f'Error checking UISP duplicate for {txn.entryId}: {e}')
        return None

def convert_lead_to_client(client_id):
    """Check if client is a lead and convert to client if needed"""
    try:
        # Get client details
        url = f"{Config.UISP_BASE_URL}clients/{client_id}"
        headers = {
            Config.UISP_AUTHORIZATION: Config.UISP_API_KEY,
            'Content-Type': 'application/json'
        }

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code != 200:
            logger.error(f'Failed to fetch client {client_id}: {response.status_code}')
            return False

        client_data = response.json()
        is_lead = client_data.get('isLead', False)

        if not is_lead:
            logger.debug(f'Client {client_id} is already a full client')
            return True

        # Convert lead to client by setting isLead=False
        logger.info(f'Converting lead {client_id} to full client...')

        patch_url = f"{Config.UISP_BASE_URL}clients/{client_id}"
        patch_data = {'isLead': False}

        patch_response = requests.patch(patch_url, json=patch_data, headers=headers, timeout=30)

        if patch_response.status_code in [200, 201]:
            logger.info(f'✅ Successfully converted lead {client_id} to client')
            log_audit(
                'CONVERT_LEAD',
                'SUCCESS',
                f'Converted lead {client_id} to client for payment processing',
                None
            )
            return True
        else:
            logger.error(f'❌ Failed to convert lead {client_id}: {patch_response.status_code} - {patch_response.text[:200]}')
            return False

    except Exception as e:
        logger.error(f'Exception while converting lead {client_id}: {e}')
        return False

def post_to_uisp(transactions):
    """Post payments to UISP API and mark as posted"""
    success_count = 0
    failed_count = 0
    duplicate_count = 0
    failed_transactions = []
    total_amount = 0.0

    for txn in transactions:
        payload = build_uisp_payload(txn)
        if not payload:
            logger.warning(f'Skipping {txn.entryId}: no valid payload')
            continue

        # Check for duplicate payment in UISP (same CID + same amount within last 15 days)
        duplicate = check_duplicate_payment(txn)
        if duplicate:
            duplicate_count += 1
            reason = f"Duplicate payment found in UISP: CID{txn.CID} already paid R{duplicate['amount']:.2f} on {duplicate['created_date'].strftime('%Y-%m-%d')} ({duplicate['days_ago']} days ago). Provider: {duplicate['provider']}, Method: {duplicate['method']}. FLAGGED FOR MANUAL REVIEW."

            # Create FailedTransaction record for manual review
            existing_failed = FailedTransaction.query.filter_by(entryId=txn.entryId).first()
            if not existing_failed:
                failed_txn = FailedTransaction(
                    entryId=txn.entryId,
                    reason=reason,
                    error_code='DUPLICATE_UISP_MANUAL_REVIEW',
                    resolved=False
                )
                db.session.add(failed_txn)
                db.session.commit()

            # Update transaction status for manual review
            txn.status = 'duplicate_manual_review'
            db.session.commit()

            logger.warning(f'⚠️  Duplicate in UISP: {txn.entryId} - {reason}')
            log_audit('POST_PAYMENT', 'DUPLICATE_UISP_MANUAL_REVIEW', reason, txn.entryId)

            failed_transactions.append({
                'entryId': txn.entryId,
                'CID': txn.CID,
                'amount': txn.amount,
                'error': reason
            })
            continue

        # Check if client is a lead and convert to client if needed
        client_id = payload.get('clientId')
        if client_id:
            if not convert_lead_to_client(client_id):
                failed_count += 1
                error_msg = f"Failed to convert lead {client_id} to client"

                existing_failed = FailedTransaction.query.filter_by(entryId=txn.entryId).first()
                if not existing_failed:
                    failed_txn = FailedTransaction(
                        entryId=txn.entryId,
                        reason=error_msg,
                        error_code='LEAD_CONVERSION_FAILED',
                        resolved=False
                    )
                    db.session.add(failed_txn)
                    db.session.commit()

                failed_transactions.append({
                    'entryId': txn.entryId,
                    'CID': txn.CID,
                    'amount': txn.amount,
                    'error': error_msg
                })
                logger.error(f'❌ Failed {txn.entryId}: {error_msg}')
                log_audit('POST_PAYMENT', 'FAILED', error_msg, txn.entryId)
                continue

        try:
            url = f"{Config.UISP_BASE_URL}payments"
            headers = {
                Config.UISP_AUTHORIZATION: Config.UISP_API_KEY,
                'Content-Type': 'application/json'
            }

            response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code in [200, 201]:
                txn.posted = 'yes'
                db.session.commit()
                total_amount += txn.amount
                success_count += 1

                log_audit(
                    'POST_PAYMENT',
                    'SUCCESS',
                    f"Posted {txn.amount} ZAR for CID {txn.CID}",
                    txn.entryId
                )
                logger.info(f'✅ Posted {txn.entryId}: {txn.amount} ZAR to CID {txn.CID}')
            else:
                failed_count += 1
                error_msg = f"{response.status_code}: {response.text[:200]}"

                # Create FailedTransaction record for manual review
                existing_failed = FailedTransaction.query.filter_by(entryId=txn.entryId).first()
                if not existing_failed:
                    failed_txn = FailedTransaction(
                        entryId=txn.entryId,
                        reason=f"UISP API error: {error_msg}",
                        error_code=str(response.status_code),
                        resolved=False
                    )
                    db.session.add(failed_txn)
                    db.session.commit()

                failed_transactions.append({
                    'entryId': txn.entryId,
                    'CID': txn.CID,
                    'amount': txn.amount,
                    'error': error_msg
                })
                logger.error(f'❌ Failed {txn.entryId}: {error_msg}')

                log_audit(
                    'POST_PAYMENT',
                    'FAILED',
                    error_msg,
                    txn.entryId
                )

        except Exception as e:
            failed_count += 1
            error_msg = str(e)

            # Create FailedTransaction record for manual review
            existing_failed = FailedTransaction.query.filter_by(entryId=txn.entryId).first()
            if not existing_failed:
                failed_txn = FailedTransaction(
                    entryId=txn.entryId,
                    reason=f"Exception during posting: {error_msg}",
                    error_code='EXCEPTION',
                    resolved=False
                )
                db.session.add(failed_txn)
                db.session.commit()

            failed_transactions.append({
                'entryId': txn.entryId,
                'CID': txn.CID,
                'amount': txn.amount,
                'error': error_msg
            })
            logger.error(f'❌ Exception posting {txn.entryId}: {e}')

            log_audit(
                'POST_PAYMENT',
                'EXCEPTION',
                error_msg,
                txn.entryId
            )

    return {
        'success_count': success_count,
        'failed_count': failed_count,
        'duplicate_count': duplicate_count,
        'total_amount': total_amount,
        'failed_transactions': failed_transactions
    }

def get_last_payment_from_uisp(cid):
    """Fetch last payment from UISP for a customer"""
    try:
        from datetime import timedelta
        today = datetime.now(timezone.utc)
        sixty_days_ago = today - timedelta(days=60)

        date_from = sixty_days_ago.strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')

        # Use v1.0 API endpoint with query parameters
        base_url = Config.UISP_BASE_URL.replace('/v2.0/', '/v1.0/')
        url = f"{base_url}payments?createdDateFrom={date_from}&createdDateTo={date_to}&clientId={cid}"

        headers = {
            Config.UISP_AUTHORIZATION: Config.UISP_API_KEY,
            'Content-Type': 'application/json'
        }

        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            payments = response.json()
            if payments:
                # Sort by created date descending to get latest first
                payments_sorted = sorted(payments, key=lambda x: x.get('createdDate', ''), reverse=True)
                return payments_sorted[0] if payments_sorted else None
        return None
    except Exception as e:
        logger.error(f'Error fetching last payment for CID {cid}: {e}')
        return None

def display_transaction_prompt(txn, index, total):
    """Display transaction details and prompt for action"""
    print("\n" + "="*80)
    print(f"Transaction {index}/{total}")
    print("="*80)
    print(f"Entry ID:         {txn.entryId}")
    print(f"Customer ID:      {txn.CID}")
    print(f"Amount:           ZAR {txn.amount:.2f}")
    print(f"Reference:        {txn.reference or 'N/A'}")
    print(f"Remittance Info:  {txn.remittance_info or 'N/A'}")
    print(f"Transaction Date: {txn.timestamp.strftime('%Y-%m-%d %H:%M:%S') if txn.timestamp else 'N/A'}")
    print(f"Note:             {txn.note or 'N/A'}")

    # Fetch and display last payment from UISP
    print("\n" + "-"*80)
    print("LAST PAYMENT IN UISP:")
    print("-"*80)

    last_payment = get_last_payment_from_uisp(txn.CID)
    if last_payment:
        created_date = datetime.fromisoformat(last_payment['createdDate'].replace('Z', '+00:00'))
        days_ago = (datetime.now(timezone.utc) - created_date).days

        print(f"Amount:           {last_payment.get('currencyCode', 'ZAR')} {last_payment.get('amount', 0):.2f}")
        print(f"Date:             {created_date.strftime('%Y-%m-%d %H:%M:%S')} ({days_ago} days ago)")
        print(f"Method:           {last_payment.get('method', {}).get('name', 'Unknown')}")
        print(f"Provider:         {last_payment.get('providerName', 'N/A')}")
        print(f"Provider ID:      {last_payment.get('providerPaymentId', 'N/A')}")
        print(f"Note:             {last_payment.get('note', 'N/A')}")

        # Warning if recent payment
        if days_ago <= 7:
            print(f"\n⚠️  WARNING: Payment was made {days_ago} days ago - possible duplicate!")
        else:
            print(f"\n✅ Last payment was {days_ago} days ago - likely safe to post")
    else:
        print("No payment history found in last 60 days")
        print("✅ This appears to be a new customer or first payment")

    print("\n" + "="*80)
    print("OPTIONS:")
    print("  [P] Post to UISP")
    print("  [M] Mark as posted (already captured manually)")
    print("  [S] Skip this transaction")
    print("  [E] End script")
    print("="*80)

def interactive_post_mode(transactions):
    """Interactive mode for posting transactions with prompts"""
    posted_count = 0
    marked_count = 0
    skipped_count = 0
    total_amount = 0.0

    for index, txn in enumerate(transactions, 1):
        display_transaction_prompt(txn, index, len(transactions))

        while True:
            choice = input("\nYour choice [P/M/S/E]: ").strip().upper()

            if choice == 'E':
                print("\n🛑 Script ended by user")
                logger.info(f'Script ended by user at transaction {index}/{len(transactions)}')
                break
            elif choice == 'S':
                print(f"⏭️  Skipped transaction {txn.entryId}")
                logger.info(f'Skipped transaction {txn.entryId}')
                skipped_count += 1
                break
            elif choice == 'M':
                # Mark as posted without API call
                txn.posted = 'yes'
                txn.UISPpaymentId = f'MANUAL_{txn.entryId}'
                txn.postedDate = datetime.now(timezone.utc)
                txn.status = 'posted_manual'
                db.session.commit()

                log_audit(txn.entryId, 'MARKED_AS_POSTED', 'posted', 'no', 'yes', 'script_interactive')
                print(f"✅ Marked {txn.entryId} as posted (CID: {txn.CID}, Amount: ZAR {txn.amount:.2f})")
                logger.info(f'Marked as posted: {txn.entryId} - CID {txn.CID}, Amount: ZAR {txn.amount:.2f}')
                marked_count += 1
                total_amount += txn.amount
                break
            elif choice == 'P':
                # Post to UISP
                payload = build_uisp_payload(txn)
                if not payload:
                    print(f"❌ Error: Could not build payload for {txn.entryId}")
                    break

                try:
                    url = f"{Config.UISP_BASE_URL}payments"
                    headers = {
                        Config.UISP_AUTHORIZATION: Config.UISP_API_KEY,
                        'Content-Type': 'application/json'
                    }

                    if Config.TEST_MODE:
                        print("\n" + "-"*80)
                        print("REQUEST DETAILS:")
                        print("-"*80)
                        print(f"URL: {url}")
                        print(f"Method: POST")
                        print(f"Headers: {headers}")
                        print(f"\nPayload:")
                        import json
                        print(json.dumps(payload, indent=2))
                        print("-"*80)

                    print(f"📤 Posting to UISP...")
                    response = requests.post(url, json=payload, headers=headers, timeout=30)

                    if Config.TEST_MODE:
                        print("\n" + "-"*80)
                        print("RESPONSE DETAILS:")
                        print("-"*80)
                        print(f"Status Code: {response.status_code}")
                        print(f"Status: {response.reason}")
                        print(f"\nResponse Headers:")
                        for key, value in response.headers.items():
                            print(f"  {key}: {value}")
                        print(f"\nResponse Body:")
                        try:
                            print(json.dumps(response.json(), indent=2))
                        except:
                            print(response.text)
                        print("-"*80 + "\n")

                    if response.status_code in [200, 201]:
                        response_data = response.json()
                        txn.posted = 'yes'
                        txn.UISPpaymentId = response_data.get('id')
                        txn.postedDate = datetime.now(timezone.utc)
                        txn.status = 'posted'
                        db.session.commit()

                        log_audit(txn.entryId, 'POSTED', 'posted', 'no', 'yes', 'script_interactive')
                        print(f"✅ Posted {txn.entryId} - CID {txn.CID}, Amount: ZAR {txn.amount:.2f}")
                        logger.info(f'Posted: {txn.entryId} - CID {txn.CID}, Amount: ZAR {txn.amount:.2f}')
                        posted_count += 1
                        total_amount += txn.amount
                    else:
                        error_msg = f"{response.status_code}: {response.text[:500]}"
                        print(f"❌ Failed to post: {error_msg}")
                        logger.error(f'Failed to post {txn.entryId}: {error_msg}')

                        # Create FailedTransaction record
                        existing_failed = FailedTransaction.query.filter_by(entryId=txn.entryId).first()
                        if not existing_failed:
                            failed_txn = FailedTransaction(
                                entryId=txn.entryId,
                                reason=f"UISP API error: {error_msg}",
                                error_code=str(response.status_code),
                                resolved=False
                            )
                            db.session.add(failed_txn)
                            db.session.commit()
                    break
                except Exception as e:
                    print(f"❌ Exception: {str(e)}")
                    print(f"Exception Type: {type(e).__name__}")
                    import traceback
                    print(f"\nFull Traceback:")
                    traceback.print_exc()
                    logger.error(f'Exception posting {txn.entryId}: {e}')
                    break
            else:
                print("Invalid choice. Please enter P, M, S, or E")

        if choice == 'E':
            break

    return {
        'posted': posted_count,
        'marked': marked_count,
        'skipped': skipped_count,
        'total_amount': total_amount
    }

def main():
    with app.app_context():
        try:
            mode = "TEST MODE" if Config.TEST_MODE else "DEPLOYMENT MODE"
            logger.info(f'Starting payment processing in {mode}')

            # In TEST_MODE, only process last 3 days; otherwise use config setting
            cutoff_days = 3 if Config.TEST_MODE else Config.POST_CUTOFF_DAYS
            cutoff_date = (datetime.utcnow() - timedelta(days=cutoff_days)).strftime('%Y-%m-%d')

            unposted = Transaction.query.filter(
                Transaction.posted == 'no',
                Transaction.CID != 'unallocated',
                Transaction.valueDate >= cutoff_date
            ).all()

            if not unposted:
                message = f'No transactions to process ({mode}, last {cutoff_days} days)'
                logger.info(message)
                update_telegram_messages('post_payments_UISP', message)
                log_execution('post_payments_UISP', 'SUCCESS', message, 0, 0, 0.0)
                return

            if Config.TEST_MODE:
                # TEST MODE: Interactive prompts
                print("\n" + "="*80)
                print("🧪 TEST MODE - INTERACTIVE PAYMENT PROCESSING")
                print("="*80)
                print(f"Found {len(unposted)} unposted transactions from last {cutoff_days} days")
                print(f"Total Amount: ZAR {sum(t.amount for t in unposted):.2f}")
                print("\nYou will be prompted for each transaction.")
                print("="*80)

                result = interactive_post_mode(unposted)

                total_amount = result['total_amount']
                message = f"TEST MODE (Interactive): Posted {result['posted']}, Marked {result['marked']}, Skipped {result['skipped']}, Amount: ZAR {total_amount:.2f}"

                print("\n" + "="*80)
                print("SUMMARY:")
                print("="*80)
                print(f"Posted to UISP:      {result['posted']}")
                print(f"Marked as posted:    {result['marked']}")
                print(f"Skipped:             {result['skipped']}")
                print(f"Total Amount:        ZAR {total_amount:.2f}")
                print("="*80)

                logger.info(message)
                update_telegram_messages('post_payments_UISP', message)
                log_execution('post_payments_UISP', 'TEST_INTERACTIVE', message, len(unposted), result['posted'] + result['marked'], total_amount)

            else:
                # DEPLOYMENT MODE: Post to UISP
                logger.info(f'Posting {len(unposted)} transactions to UISP...')
                result = post_to_uisp(unposted)

                success = result['success_count']
                failed = result['failed_count']
                duplicates = result['duplicate_count']
                total = len(unposted)
                amount = result['total_amount']

                message = f'DEPLOYMENT: Posted {success}/{total} payments, Amount: ZAR {amount:.2f}'
                if duplicates > 0:
                    message += f' | Duplicates: {duplicates} (flagged for manual review)'
                if failed > 0:
                    message += f' | Failed: {failed}'
                    # Dump failed transactions to file
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    failed_file = os.path.join(DUMP_DIR, f'failed_posts_{timestamp}.json')
                    with open(failed_file, 'w') as f:
                        json.dump(result['failed_transactions'], f, indent=2)
                    message += f' (failures saved to {failed_file})'

                logger.info(message)
                update_telegram_messages('post_payments_UISP', message)
                log_execution('post_payments_UISP', 'SUCCESS', message, total, success, amount)

        except Exception as e:
            logger.error(f'Process failed: {e}')
            log_execution('post_payments_UISP', 'FAILED', str(e))
            update_telegram_messages('post_payments_UISP', f'Error: {e}')

if __name__ == '__main__':
    main()
