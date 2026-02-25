from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, flash
from flask_login import login_required, current_user
from app import db, csrf
from app.models import Transaction, FailedTransaction, AuditLog, ExecutionLog, UISPPayment, Service, Customer, CachedPayment
from app.utils import resolve_failed_transaction, log_audit, log_user_activity, fetch_fnb_transactions_by_period, get_suggested_cid
from app.auth import admin_required
from app.config import Config
from app.uisp_analyzer import (
    fetch_uisp_payments, store_uisp_payments,
    find_duplicate_payments, analyze_incorrect_references,
    get_duplicate_analysis_summary
)
import requests
from datetime import datetime, timezone
import logging

main_bp = Blueprint('main', __name__)
logger = logging.getLogger(__name__)

@main_bp.route('/')
@login_required
def index():
    stats = {
        'total_transactions': Transaction.query.count(),
        'posted': Transaction.query.filter_by(posted='yes').count(),
        'pending': Transaction.query.filter_by(posted='no').count(),
        'failed': FailedTransaction.query.filter_by(resolved=False).count(),
    }
    # Clear login sync notification flags after displaying
    session.pop('login_sync_success', None)
    session.pop('login_sync_error', None)
    session.pop('login_sync_count', None)
    session.pop('login_sync_total', None)
    return render_template('index.html', stats=stats)

@main_bp.route('/transactions', methods=['GET'])
@login_required
def list_transactions():
    # Get query parameters
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # Build base query
    query = Transaction.query

    # Apply date range filter (if provided)
    if date_from:
        query = query.filter(Transaction.valueDate >= date_from)
    if date_to:
        query = query.filter(Transaction.valueDate <= date_to)

    # Apply search filter (fuzzy search on description + reference)
    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                Transaction.original_remittance_info.like(search_pattern),
                Transaction.original_reference.like(search_pattern),
                Transaction.remittance_info.like(search_pattern),
                Transaction.reference.like(search_pattern),
                Transaction.entryId.like(search_pattern),
                Transaction.account.like(search_pattern)
            )
        )

    # Order by date descending (newest first)
    query = query.order_by(Transaction.valueDate.desc(), Transaction.timestamp.desc())

    # Paginate results (100 per page for analysis work)
    transactions = query.paginate(page=page, per_page=100, error_out=False)

    # Calculate summary stats for the filtered results
    total_amount = 0
    if transactions.items:
        result = db.session.query(db.func.sum(Transaction.amount))

        # Apply same filters as main query
        if date_from:
            result = result.filter(Transaction.valueDate >= date_from)
        if date_to:
            result = result.filter(Transaction.valueDate <= date_to)

        if search:
            search_pattern = f'%{search}%'
            result = result.filter(
                db.or_(
                    Transaction.original_remittance_info.like(search_pattern),
                    Transaction.original_reference.like(search_pattern),
                    Transaction.remittance_info.like(search_pattern),
                    Transaction.reference.like(search_pattern),
                    Transaction.entryId.like(search_pattern),
                    Transaction.account.like(search_pattern)
                )
            )

        total_amount = result.scalar() or 0

    return render_template(
        'transactions.html',
        transactions=transactions,
        search=search,
        date_from=date_from,
        date_to=date_to,
        total_amount=total_amount
    )

@main_bp.route('/transactions/query_api', methods=['POST'])
@login_required
def query_api_transactions():
    """Query FNB API directly for transactions matching CID and/or search text"""
    try:
        # Get form data
        from_date = request.form.get('api_from_date', '').strip()
        to_date = request.form.get('api_to_date', '').strip()
        cid = request.form.get('api_cid', '').strip()
        search_text = request.form.get('api_search_text', '').strip()

        # Validate required date fields
        if not from_date or not to_date:
            flash('From date and to date are required', 'danger')
            return redirect(url_for('main.list_transactions'))

        # Normalize CID format (remove "CID" prefix if present)
        if cid:
            import re
            cid_match = re.search(r'\d+', cid)
            if cid_match:
                cid = cid_match.group()
            else:
                flash('Invalid CID format. Please provide a numeric CID (e.g., 818 or CID818)', 'danger')
                return redirect(url_for('main.list_transactions'))

        # Validate at least one search criterion
        if not cid and not search_text:
            flash('Please provide at least one search criterion (CID or search text)', 'danger')
            return redirect(url_for('main.list_transactions'))

        # Fetch transactions from FNB API
        try:
            matched_entries = fetch_fnb_transactions_by_period(from_date, to_date, cid, search_text)
        except ValueError as e:
            flash(f'Invalid date range: {str(e)}', 'danger')
            return redirect(url_for('main.list_transactions'))
        except Exception as e:
            error_msg = str(e)
            if 'timed out' in error_msg.lower():
                flash('FNB API request timed out. Please try again.', 'danger')
            elif 'authenticate' in error_msg.lower():
                flash('Failed to authenticate with FNB API. Please check configuration.', 'danger')
            else:
                flash(f'Error querying FNB API: {error_msg}', 'danger')
            return redirect(url_for('main.list_transactions'))

        # Convert API entries to transaction-like format for template
        api_results = []
        for entry in matched_entries:
            try:
                # Extract transaction details from nested FNB API structure
                entry_details = entry.get('entryDetails', {})
                txn_details = entry_details.get('transactionDetails', {})
                remittance = txn_details.get('remittanceInfo', {}).get('unstructured', '')
                reference = txn_details.get('reference', {}).get('endToEndId', '')
                amount_data = entry.get('amount', {}).get('amount', 0)
                date_data = entry.get('valueDate', {}).get('Date', '')
                entry_id = entry.get('entryId', '')

                # Get account number that was added during API fetch
                account = entry.get('account_number', 'Unknown')

                api_results.append({
                    'entryId': entry_id,
                    'amount': float(amount_data) if amount_data else 0,
                    'valueDate': date_data,
                    'remittance_info': remittance,
                    'reference': reference,
                    'account': account,
                    'CID': cid if cid else 'unallocated',
                    'posted': 'no',
                    'status': 'api_result',
                    'source': 'FNB API'
                })
            except Exception as e:
                logger.error(f"Error formatting API transaction: {e}")
                continue

        # Prepare context for template
        query_params = {
            'cid': cid,
            'search_text': search_text,
            'from_date': from_date,
            'to_date': to_date
        }

        return render_template(
            'transactions.html',
            api_results=api_results,
            query_params=query_params,
            result_count=len(api_results),
            transactions=None,
            search='',
            date_from='',
            date_to='',
            total_amount=0
        )

    except Exception as e:
        logger.error(f"Unexpected error in query_api_transactions: {e}")
        flash('An unexpected error occurred. Please try again.', 'danger')
        return redirect(url_for('main.list_transactions'))

@main_bp.route('/failed', methods=['GET'])
@login_required
def failed_transactions():
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Get failed transactions
    failed_query = FailedTransaction.query.filter_by(resolved=False)
    failed_docs = failed_query.all()

    # Get unallocated transactions (treat as failed)
    unallocated = Transaction.query.filter_by(CID='unallocated', posted='no').all()

    # Combine both lists
    data = []

    # Keep track of entry IDs that have failed records
    failed_entry_ids = {f.entryId for f in failed_docs}

    # Add failed transactions
    for f in failed_docs:
        # If there are multiple transactions with same entryId, get the correct one
        all_txns = Transaction.query.filter_by(entryId=f.entryId).all()
        txn = None
        if len(all_txns) > 1:
            # Multiple transactions - prefer the one with unallocated CID
            txn = next((t for t in all_txns if t.CID == 'unallocated'), all_txns[0])
        else:
            txn = all_txns[0] if all_txns else None

        if txn:
            data.append({
                'failed': f,
                'transaction': txn,
                'type': 'failed',
                'is_duplicate': f.error_code == 'DUPLICATE'
            })

    # Add unallocated transactions (but exclude those already in failed_transactions)
    for txn in unallocated:
        # Skip if this entry ID already has a failed record
        if txn.entryId not in failed_entry_ids:
            data.append({
                'failed': None,
                'transaction': txn,
                'type': 'unallocated',
                'is_duplicate': False
            })

    # Paginate manually
    total = len(data)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_data = data[start:end]

    # Create pagination object
    class Pagination:
        def __init__(self, page, per_page, total):
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = (total + per_page - 1) // per_page if total > 0 else 1
            self.has_prev = page > 1
            self.has_next = page < self.pages
            self.prev_num = page - 1 if self.has_prev else None
            self.next_num = page + 1 if self.has_next else None

        def iter_pages(self, left_edge=2, left_current=2, right_current=3, right_edge=2):
            last = 0
            for num in range(1, self.pages + 1):
                if num <= left_edge or \
                   (num > self.page - left_current - 1 and num < self.page + right_current) or \
                   num > self.pages - right_edge:
                    if last + 1 != num:
                        yield None
                    yield num
                    last = num

    pagination = Pagination(page, per_page, total)

    return render_template('failed.html', failures=paginated_data, pagination=pagination)

@main_bp.route('/api/failed/<entry_id>', methods=['GET'])
@login_required
def get_failed_transaction(entry_id):
    # If there are multiple failed transaction records for same entryId,
    # prefer the unresolved one or the one with BUG_ENTRY_ID_CONFLICT
    all_failed = FailedTransaction.query.filter_by(entryId=entry_id).all()

    failed = None
    if all_failed:
        # Prefer unresolved records
        failed = next((f for f in all_failed if not f.resolved), None)
        if not failed:
            # Prefer bug explanation records
            failed = next((f for f in all_failed if 'BUG_ENTRY_ID_CONFLICT' in f.error_code), None)
        if not failed:
            # Fall back to first one
            failed = all_failed[0]

    # If there are multiple transactions with same entryId (cross-account duplicates),
    # we need to find the one in failed_transactions or the one with unallocated CID
    # Order by CID (unallocated first) then by ID for consistent selection
    all_txns = Transaction.query.filter_by(entryId=entry_id).order_by(
        (Transaction.CID == 'unallocated').desc(),
        Transaction.id.asc()
    ).all()

    txn = None
    if len(all_txns) > 1 and failed:
        # Multiple transactions - always use the first one after ordering
        # (unallocated transactions come first)
        txn = all_txns[0]
    else:
        # Single transaction or no failed record
        txn = all_txns[0] if all_txns else None

    if not txn:
        return jsonify({'error': 'Not found'}), 404

    is_duplicate = failed.error_code == 'DUPLICATE' if failed else False

    # Get suggested CID from EFT mapping
    suggested_cid = get_suggested_cid(txn)

    return jsonify({
        'entryId': txn.entryId,
        'amount': txn.amount,
        'reference': txn.reference,
        'remittance_info': txn.remittance_info,
        'current_cid': txn.CID,
        'suggested_cid': suggested_cid,
        'reason': failed.reason if failed else None,
        'is_duplicate': is_duplicate,
        'account': txn.account,
        'txn_id': txn.id
    })

@main_bp.route('/update_cid/<entry_id>', methods=['POST'])
@login_required
@csrf.exempt
def update_cid(entry_id):
    """Update CID for a transaction and optionally post it"""
    import re
    cid_input = request.form.get('cid', '').strip()
    note = request.form.get('note', '').strip()
    post_now = request.form.get('post_now') == 'yes'
    mark_as_posted = request.form.get('mark_as_posted') == 'yes'

    if not cid_input:
        return jsonify({'error': 'CID required'}), 400

    try:
        # If there are multiple transactions with same entryId, get the correct one
        # Order by CID (unallocated first) then by ID for consistent selection
        all_txns = Transaction.query.filter_by(entryId=entry_id).order_by(
            (Transaction.CID == 'unallocated').desc(),
            Transaction.id.asc()
        ).all()
        failed = FailedTransaction.query.filter_by(entryId=entry_id).first()

        txn = None
        if len(all_txns) > 1 and failed:
            # Multiple transactions - always use the first one after ordering
            # (unallocated transactions come first)
            txn = all_txns[0]
        else:
            txn = all_txns[0] if all_txns else None

        if not txn:
            return jsonify({'error': 'Transaction not found'}), 404

        # Extract numeric portion from CID (handle both "123" and "CID123" formats)
        cid_match = re.search(r'\d+', cid_input)
        if not cid_match:
            return jsonify({'error': 'CID must contain numbers'}), 400
        cid = cid_match.group()

        # Update CID and note (store only the numeric portion)
        old_cid = txn.CID
        txn.CID = cid
        if note:
            txn.note = note

        # Remove from FailedTransaction if it exists
        failed = FailedTransaction.query.filter_by(entryId=entry_id).first()
        if failed:
            failed.resolved = True
            failed.resolved_at = datetime.now(timezone.utc)
            failed.manual_cid = cid

        # Handle mark as posted (skip UISP API call)
        if mark_as_posted:
            txn.posted = 'yes'
            txn.UISPpaymentId = f'MANUAL_{entry_id}'
            txn.postedDate = datetime.now(timezone.utc)
            txn.status = 'posted_manual'
            db.session.commit()
            log_audit(entry_id, 'UPDATE_CID', 'CID', old_cid, cid, 'web_gui')
            log_audit(entry_id, 'MARKED_AS_POSTED', 'posted', 'no', 'yes', 'web_gui_manual')
            logger.info(f'Marked {entry_id} as manually posted (CID: {cid})')
            return jsonify({'status': 'success', 'message': 'CID updated and marked as posted', 'entryId': entry_id})

        db.session.commit()
        log_audit(entry_id, 'UPDATE_CID', 'CID', old_cid, cid, 'web_gui')

        # Post if requested
        if post_now:
            result = post_payment_uisp(txn)
            if result:
                return jsonify({'status': 'success', 'message': 'CID updated and posted', 'entryId': entry_id})
            else:
                return jsonify({'status': 'partial', 'message': 'CID updated but posting failed', 'entryId': entry_id})

        return jsonify({'status': 'success', 'message': 'CID updated successfully', 'entryId': entry_id})
    except Exception as e:
        logger.error(f'Error updating CID for {entry_id}: {e}')
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@main_bp.route('/api/resolve/<entry_id>', methods=['POST'])
@login_required
@csrf.exempt
def resolve_transaction(entry_id):
    data = request.get_json()
    manual_cid = data.get('manual_cid')

    if not manual_cid:
        return jsonify({'error': 'manual_cid required'}), 400

    try:
        resolve_failed_transaction(entry_id, manual_cid)

        # If there are multiple transactions with same entryId, get the correct one
        # Order by CID (unallocated first) then by ID for consistent selection
        all_txns = Transaction.query.filter_by(entryId=entry_id).order_by(
            (Transaction.CID == 'unallocated').desc(),
            Transaction.id.asc()
        ).all()
        failed = FailedTransaction.query.filter_by(entryId=entry_id).first()

        txn = None
        if len(all_txns) > 1 and failed:
            # Multiple transactions - always use the first one after ordering
            # (unallocated transactions come first)
            txn = all_txns[0]
        else:
            txn = all_txns[0] if all_txns else None

        # Attempt to post immediately
        post_payment_uisp(txn)

        return jsonify({'status': 'resolved', 'entryId': entry_id})
    except Exception as e:
        logger.error(f'Error resolving {entry_id}: {e}')
        return jsonify({'error': str(e)}), 500

def post_payment_uisp(txn):
    """Post a transaction to UISP (GUI always posts, ignores TEST_MODE)"""
    import json
    import os
    import re
    try:
        # Extract numeric portion from CID (handle both "123" and "CID123" formats)
        cid_str = str(txn.CID).strip()
        cid_match = re.search(r'\d+', cid_str)
        if not cid_match:
            raise ValueError(f"Invalid CID format: {cid_str} - must contain numbers")
        uisp_cid = int(cid_match.group())
        amount = float(txn.amount)
        entryId = txn.entryId

        formatted_note = f"{txn.note or ''} | TXN ID: {entryId}".strip(' |')
        provider_payment_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S%z')

        payload = {
            'clientId': uisp_cid,
            'methodId': Config.UISP_PAYMENT_METHOD_ID,
            'currencyCode': 'ZAR',
            'applyToInvoicesAutomatically': True,
            'providerPaymentId': entryId,
            'providerPaymentTime': provider_payment_time,
            'providerName': 'FNB-EFT',
            'amount': amount,
            'userId': Config.UISP_USER_ID,
            'note': formatted_note
        }

        # GUI ALWAYS POSTS TO UISP (ignores TEST_MODE)
        url = f"{Config.UISP_BASE_URL}payments"
        headers = {
            Config.UISP_AUTHORIZATION: Config.UISP_API_KEY,
            'Content-Type': 'application/json'
        }

        logger.info(f'GUI Posting to UISP: {entryId} - CID {uisp_cid}, Amount: {amount} ZAR')
        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if response.status_code in [200, 201]:
            response_data = response.json()

            # Update transaction as posted
            txn.posted = 'yes'
            txn.UISPpaymentId = response_data.get('id')
            txn.postedDate = datetime.now(timezone.utc)
            txn.status = 'posted'
            db.session.commit()

            log_audit(txn.entryId, 'POSTED_MANUAL', 'posted', 'no', 'yes', 'web_gui')
            logger.info(f'✅ Posted {entryId}: {amount} ZAR to CID {uisp_cid} via GUI (UISP ID: {response_data.get("id")})')
            return True
        else:
            error_msg = f"{response.status_code}: {response.text[:200]}"
            logger.error(f'❌ Failed to post {entryId}: {error_msg}')

            # Log full response for debugging
            logger.error(f'Full response: Status={response.status_code}, Body={response.text[:500]}')
            return False

    except Exception as e:
        logger.error(f'Error posting {txn.entryId}: {e}')
        return False

@main_bp.route('/audit/<entry_id>', methods=['GET'])
@login_required
def audit_log(entry_id):
    logs = AuditLog.query.filter_by(entryId=entry_id).order_by(AuditLog.timestamp.desc()).all()
    return render_template('audit.html', logs=logs, entry_id=entry_id)

@main_bp.route('/execution-logs', methods=['GET'])
@admin_required
def execution_logs():
    page = request.args.get('page', 1, type=int)
    logs = ExecutionLog.query.order_by(ExecutionLog.timestamp.desc()).paginate(page=page, per_page=50)
    return render_template('execution_logs.html', logs=logs)

@main_bp.route('/bulk_update_transactions', methods=['POST'])
@login_required
@csrf.exempt
def bulk_update_transactions():
    """Bulk update multiple transactions with CID and notes"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'error': 'Invalid request: No JSON data provided'}), 400

        updates = data.get('updates', [])
        if not updates:
            return jsonify({'status': 'error', 'error': 'No updates provided. Please fill in CIDs for all transactions.'}), 400
    except Exception as e:
        logger.error(f'Error parsing bulk update request: {e}')
        return jsonify({'status': 'error', 'error': f'Invalid request format: {str(e)}'}), 400

    updated_count = 0
    errors = []

    for update in updates:
        entry_id = update.get('entryId')
        cid = update.get('cid', '').strip()
        note = update.get('note', '').strip()
        mark_as_posted = update.get('markAsPosted', False)

        if not entry_id or not cid:
            errors.append(f'{entry_id}: Missing CID')
            continue

        try:
            # If there are multiple transactions with same entryId, get the correct one
            # Order by CID (unallocated first) then by ID for consistent selection
            all_txns = Transaction.query.filter_by(entryId=entry_id).order_by(
                (Transaction.CID == 'unallocated').desc(),
                Transaction.id.asc()
            ).all()
            failed = FailedTransaction.query.filter_by(entryId=entry_id).first()

            txn = None
            if len(all_txns) > 1 and failed:
                # Multiple transactions - always use the first one after ordering
                # (unallocated transactions come first)
                txn = all_txns[0]
            else:
                txn = all_txns[0] if all_txns else None

            if not txn:
                errors.append(f'{entry_id}: Transaction not found')
                continue

            # Update CID and note (strip any whitespace from CID)
            old_cid = txn.CID
            txn.CID = str(cid).strip()
            if note:
                txn.note = note

            # Remove from FailedTransaction if it exists
            if failed:
                failed.resolved = True
                failed.resolved_at = datetime.now(timezone.utc)
                failed.manual_cid = cid

            # Handle posting based on markAsPosted flag
            if mark_as_posted:
                # Mark as manually posted (skip UISP API call)
                txn.posted = 'yes'
                txn.UISPpaymentId = f'MANUAL_{entry_id}'
                txn.postedDate = datetime.now(timezone.utc)
                txn.status = 'posted_manual'
                log_audit(entry_id, 'MARKED_AS_POSTED', 'posted', 'no', 'yes', 'bulk_edit_manual')
                logger.info(f'Marked {entry_id} as manually posted (CID: {cid})')
            else:
                # Post via UISP (respects TEST_MODE)
                post_result = post_payment_uisp(txn)
                if not post_result:
                    errors.append(f'{entry_id}: Failed to post to UISP')
                    continue

            db.session.commit()
            log_audit(entry_id, 'BULK_UPDATE_CID', 'CID', old_cid, cid, 'bulk_edit')
            updated_count += 1

        except Exception as e:
            logger.error(f'Error updating {entry_id}: {e}')
            db.session.rollback()
            errors.append(f'{entry_id}: {str(e)}')
            continue

    result = {
        'status': 'success' if updated_count > 0 else 'error',
        'updated': updated_count,
        'errors': errors
    }

    if errors:
        result['message'] = f'Updated {updated_count} transactions with {len(errors)} errors'
    else:
        result['message'] = f'Successfully updated {updated_count} transactions'

    return jsonify(result)

@main_bp.route('/api/customer_payments/<cid>', methods=['GET'])
@login_required
def get_customer_payments(cid):
    """Fetch customer payment history from UISP"""
    try:
        # Calculate date range for last 60 days
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

            # Sort by created date descending to get latest first
            if payments:
                payments_sorted = sorted(payments, key=lambda x: x.get('createdDate', ''), reverse=True)

                # Get last 5 payments with relevant info
                recent_payments = []
                for payment in payments_sorted[:5]:
                    recent_payments.append({
                        'id': payment.get('id'),
                        'amount': payment.get('amount'),
                        'currencyCode': payment.get('currencyCode', 'ZAR'),
                        'createdDate': payment.get('createdDate'),
                        'method': payment.get('method', {}).get('name', 'Unknown'),
                        'note': payment.get('note', ''),
                        'providerPaymentId': payment.get('providerPaymentId', ''),
                        'providerName': payment.get('providerName', '')
                    })

                return jsonify({
                    'status': 'success',
                    'cid': cid,
                    'total_payments': len(payments),
                    'recent_payments': recent_payments
                })
            else:
                return jsonify({
                    'status': 'success',
                    'cid': cid,
                    'total_payments': 0,
                    'recent_payments': [],
                    'message': 'No payment history found for this customer'
                })
        elif response.status_code == 404:
            return jsonify({
                'status': 'error',
                'message': f'Customer CID {cid} not found in UISP'
            }), 404
        else:
            return jsonify({
                'status': 'error',
                'message': f'UISP API error: {response.status_code}'
            }), response.status_code

    except requests.exceptions.Timeout:
        return jsonify({
            'status': 'error',
            'message': 'UISP API timeout - please try again'
        }), 504
    except Exception as e:
        logger.error(f'Error fetching payments for CID {cid}: {e}')
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@main_bp.route('/api/customer_info/<cid>', methods=['GET'])
@login_required
def get_customer_info(cid):
    """Fetch customer balance and last 2 payments"""
    try:
        # Extract numeric CID
        numeric_cid = int(str(cid).replace('CID', '').strip())

        # Get customer from local cache
        customer = Customer.query.filter_by(uisp_client_id=numeric_cid).first()

        if not customer:
            return jsonify({
                'status': 'not_found',
                'message': f'Customer {numeric_cid} not found in system'
            }), 404

        # Get last 2 payments
        last_payments = CachedPayment.query.filter_by(customer_id=customer.id)\
            .order_by(CachedPayment.created_date.desc())\
            .limit(2)\
            .all()

        payments_data = []
        for payment in last_payments:
            payments_data.append({
                'amount': payment.amount,
                'date': payment.created_date.strftime('%Y-%m-%d %H:%M') if payment.created_date else '',
                'method': payment.method or 'N/A',
                'note': payment.note or ''
            })

        result = {
            'status': 'success',
            'customer_id': numeric_cid,
            'name': f"{customer.first_name or ''} {customer.last_name or ''}".strip() or 'N/A',
            'email': customer.email or 'N/A',
            'phone': customer.phone or 'N/A',
            'account_balance': round(customer.account_balance, 2),
            'account_outstanding': round(customer.account_outstanding, 2),
            'account_credit': round(customer.account_credit, 2),
            'is_active': customer.is_active,
            'is_archived': customer.is_archived,
            'is_vip': customer.is_vip,
            'has_overdue_invoice': customer.has_overdue_invoice,
            'last_2_payments': payments_data,
            'cached_at': customer.cached_at.strftime('%Y-%m-%d %H:%M') if customer.cached_at else ''
        }

        return jsonify(result)

    except ValueError:
        return jsonify({
            'status': 'error',
            'message': 'Invalid CID format'
        }), 400
    except Exception as e:
        logger.error(f'Error fetching customer info: {e}')
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@main_bp.route('/customer-analysis', methods=['GET'])
@login_required
def customer_analysis():
    """Customer analysis page with duplicate payments and incorrect references"""
    action = request.args.get('action')

    # Fetch fresh UISP payments if requested
    if action == 'refresh':
        try:
            payments = fetch_uisp_payments(months=6)
            new_count, updated_count = store_uisp_payments(payments)
            logger.info(f"Refreshed UISP payments: {new_count} new, {updated_count} updated")
        except Exception as e:
            logger.error(f"Error refreshing UISP payments: {e}")

    # Get statistics
    total_uisp_payments = UISPPayment.query.count()
    last_fetch = UISPPayment.query.order_by(UISPPayment.fetched_at.desc()).first()
    last_fetch_time = last_fetch.fetched_at if last_fetch else None

    # Get duplicate analysis
    duplicates_1m = find_duplicate_payments(30)
    duplicates_3m = find_duplicate_payments(90)
    duplicates_6m = find_duplicate_payments(180)

    # Get incorrect references analysis
    incorrect_refs = analyze_incorrect_references()

    stats = {
        'total_uisp_payments': total_uisp_payments,
        'last_fetch': last_fetch_time,
        'duplicates_1month': {
            'clients_affected': len(duplicates_1m),
            'total_issues': sum(len(issues) for issues in duplicates_1m.values())
        },
        'duplicates_3months': {
            'clients_affected': len(duplicates_3m),
            'total_issues': sum(len(issues) for issues in duplicates_3m.values())
        },
        'duplicates_6months': {
            'clients_affected': len(duplicates_6m),
            'total_issues': sum(len(issues) for issues in duplicates_6m.values())
        },
        'incorrect_references': {
            'clients_affected': len(incorrect_refs),
            'total_issues': sum(len(issues) for issues in incorrect_refs.values())
        }
    }

    return render_template('customer_analysis.html',
                         stats=stats,
                         duplicates_1m=duplicates_1m,
                         duplicates_3m=duplicates_3m,
                         duplicates_6m=duplicates_6m,
                         incorrect_refs=incorrect_refs)

@main_bp.route('/transaction-history', methods=['GET'])
@login_required
def transaction_history():
    """Display last 45 days of received transactions (positive amounts only)"""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str).strip()
    status = request.args.get('status', 'all', type=str)
    per_page = 50

    # Calculate 45 days ago
    from datetime import timedelta
    today = datetime.now(timezone.utc)
    cutoff_date = today - timedelta(days=45)

    # Build query for positive amounts only, last 45 days
    query = Transaction.query.filter(
        Transaction.amount > 0,
        Transaction.timestamp >= cutoff_date
    )

    # Apply status filter
    if status == 'yes':
        query = query.filter(Transaction.posted == 'yes')
    elif status == 'no':
        query = query.filter(Transaction.posted == 'no')
    # If status == 'all', don't filter by posted status

    # Apply search filter if provided
    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                Transaction.entryId.like(search_pattern),
                Transaction.CID.like(search_pattern),
                Transaction.reference.like(search_pattern),
                Transaction.remittance_info.like(search_pattern),
                Transaction.account.like(search_pattern)
            )
        )

    # Order by timestamp descending (newest first)
    transactions = query.order_by(Transaction.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Calculate totals for current filter
    total_amount = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.amount > 0,
        Transaction.timestamp >= cutoff_date
    )

    # Apply same status filter to totals
    if status == 'yes':
        total_amount = total_amount.filter(Transaction.posted == 'yes')
    elif status == 'no':
        total_amount = total_amount.filter(Transaction.posted == 'no')

    total_amount = total_amount.scalar() or 0.0
    total_count = query.count()

    return render_template('transaction_history.html',
                         transactions=transactions,
                         search=search,
                         status=status,
                         total_amount=total_amount,
                         total_count=total_count,
                         cutoff_date=cutoff_date)

@main_bp.route('/quotes', methods=['GET'])
@login_required
def quotes():
    """Display open quotes from UISP with customer details."""
    from app.uisp_suspension_handler import UISPSuspensionHandler

    handler = UISPSuspensionHandler()

    # Get filter parameter for showing only active services
    filter_type = request.args.get('filter', 'all')

    try:
        # Fetch open quotes (status=0)
        quotes_response = handler._make_request('GET', 'v1.0/quotes', params={'statuses[]': '0'})

        # Handle both list and dict responses
        if isinstance(quotes_response, dict) and 'data' in quotes_response:
            quotes_list = quotes_response['data']
        elif isinstance(quotes_response, list):
            quotes_list = quotes_response
        else:
            quotes_list = []

        # Fetch all non-archived clients to match with quotes
        clients_response = handler._make_request('GET', 'v1.0/clients', params={'isArchived': '0'})

        if isinstance(clients_response, dict) and 'data' in clients_response:
            clients_list = clients_response['data']
        elif isinstance(clients_response, list):
            clients_list = clients_response
        else:
            clients_list = []

        # Create a map of client IDs to client data (exclude archived)
        client_map = {}
        for client in clients_list:
            is_archived = client.get('isArchived', False)
            # Check if not archived (0, False, or falsy values mean not archived)
            if not is_archived or is_archived == 0:
                client_map[client.get('id')] = client

        # Fetch active service IDs if filtering by active services
        active_service_ids_set = None
        if filter_type == 'active':
            active_service_ids = db.session.query(Service.uisp_service_id)\
                .filter(Service.status == 'active')\
                .all()
            active_service_ids_set = {sid[0] for sid in active_service_ids}
            logger.info(f"Found {len(active_service_ids_set)} active services for filtering")

        # Enrich quotes with client data
        enriched_quotes = []
        for quote in quotes_list:
            client_id = quote.get('clientId')
            client = client_map.get(client_id)

            # Only include quotes from non-archived customers
            if client:
                service_id = quote.get('serviceId')

                # Apply active service filter if enabled
                if filter_type == 'active':
                    # Skip if no service_id or service not active
                    if not service_id or service_id not in active_service_ids_set:
                        continue

                enriched_quotes.append({
                    'quote': quote,
                    'client': client,
                    'quote_id': quote.get('id'),
                    'quote_number': quote.get('number'),
                    'service_id': quote.get('serviceId'),
                    'price': quote.get('price'),
                    'total': quote.get('total'),
                    'discount_value': quote.get('discountValue'),
                    'currency_code': quote.get('currencyCode'),
                    'valid_until': quote.get('validUntil'),
                    'created_date': quote.get('createdDate'),
                    'cid': client.get('id'),
                    'full_name': client.get('fullName'),
                    'email': client.get('email'),
                    'phone': client.get('phone'),
                })

        # Sort by created date (newest first)
        enriched_quotes.sort(
            key=lambda x: x['created_date'] or '0000-00-00',
            reverse=True
        )

        logger.info(f"Fetched {len(enriched_quotes)} open quotes for non-archived customers")

        return render_template('quotes.html', quotes=enriched_quotes, filter_type=filter_type)

    except Exception as e:
        logger.error(f"Error fetching quotes: {str(e)}")
        return render_template('quotes.html', quotes=[], error=str(e), filter_type=filter_type)


@main_bp.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})
