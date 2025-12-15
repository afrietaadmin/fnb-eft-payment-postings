"""
Suspension management routes for the web UI.
Handles customer suspension, service reactivation, and reporting.
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models import Customer, Service, Suspension, PaymentPattern, Invoice
from app.uisp_suspension_handler import UISPSuspensionHandler
from app.utils import log_audit, log_user_activity
from app.config import Config
from datetime import datetime, timezone
import logging

suspension_bp = Blueprint('suspension', __name__, url_prefix='/suspensions')
logger = logging.getLogger(__name__)
handler = UISPSuspensionHandler()


@suspension_bp.route('/', methods=['GET'])
@login_required
def list_suspensions():
    """List all suspensions or fetch active suspended services from UISP."""
    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('filter', 'all')  # all, active, resolved, candidates

    if filter_type == 'active':
        # Active suspensions: Fetch directly from UISP (status=3)
        return _get_active_suspensions_from_uisp(page)
    else:
        # For other filters, use database records
        query = Suspension.query

        if filter_type == 'resolved':
            # Resolved suspensions: where is_active=False AND reactivation_date is set
            query = query.filter(Suspension.is_active == False, Suspension.reactivation_date != None)
        elif filter_type == 'candidates':
            # These are customers that SHOULD be suspended but aren't yet
            pass

        suspensions = query.order_by(Suspension.suspension_date.desc()).paginate(page=page, per_page=50)
        return render_template('suspensions/list.html', suspensions=suspensions, filter_type=filter_type)


def _get_active_suspensions_from_uisp(page):
    """Fetch active suspended services directly from UISP API."""
    try:
        # Fetch suspended services from UISP (status=3)
        suspended_services = handler.fetch_suspended_services()

        if not suspended_services:
            # Create empty pagination object
            class Pagination:
                def __init__(self):
                    self.page = page
                    self.pages = 1
                    self.items = []
                    self.has_prev = False
                    self.has_next = False

            return render_template('suspensions/list.html', suspensions=Pagination(), filter_type='active')

        # Define UISPSuspension class outside the loop
        class UISPSuspension:
            def __init__(self, service_data, customer):
                self.id = None
                self.customer = customer
                self.uisp_service_id = service_data.get('id')
                self.uisp_service_name = service_data.get('serviceName')
                self.suspension_reason = 'Suspended in UISP (no local record)'
                self.suspended_by = 'External/UISP'
                self.suspension_date = None
                self.is_active = True
                self.uisp_service_status = 'suspended'
                self.billing_amount = service_data.get('billingAmount')
                self.note = 'Service is suspended in UISP but has no suspension record in our system'

                # Parse suspension periods from UISP data
                suspension_periods = service_data.get('suspensionPeriods', [])
                self.suspension_count = len(suspension_periods)
                self.latest_suspension_date = None
                self.suspension_days = 0

                if suspension_periods:
                    try:
                        latest_suspension = suspension_periods[-1]
                        suspension_start = latest_suspension.get('startDate')
                        if suspension_start:
                            # Parse ISO format datetime
                            from datetime import datetime
                            dt_aware = datetime.fromisoformat(
                                suspension_start.replace('Z', '+00:00')
                            )
                            # Store as naive UTC (strip timezone info)
                            self.latest_suspension_date = dt_aware.replace(tzinfo=None)
                            # Calculate days suspended
                            days_suspended = (datetime.utcnow() - self.latest_suspension_date).days
                            self.suspension_days = max(0, days_suspended)
                    except Exception as e:
                        logger.warning(f"Error parsing suspension dates for service {self.uisp_service_id}: {str(e)}")

        # Build suspension objects from UISP data
        suspensions_data = []

        for service_data in suspended_services:
            service_id = service_data.get('id')
            client_id = service_data.get('clientId')

            # Get or create customer record
            customer = Customer.query.filter_by(uisp_client_id=client_id).first()

            if not customer:
                # Fetch customer from UISP if not in local DB
                customer = handler.fetch_and_cache_client(client_id)

            if not customer:
                logger.warning(f"Could not fetch customer {client_id} for service {service_id}")
                continue  # Skip if customer not found

            # Always refresh customer data from UISP to get current archived status
            # This prevents filtering out stale cached data
            customer = handler.fetch_and_cache_client(client_id)
            if not customer:
                logger.warning(f"Could not refresh customer {client_id} for service {service_id}")
                continue

            # Skip archived customers
            if customer.is_archived:
                logger.info(f"Skipping archived customer {client_id} for service {service_id}")
                continue

            # Check if we have a suspension record for this service
            suspension = Suspension.query.filter_by(
                uisp_service_id=service_id,
                is_active=True
            ).first()

            # Create a suspension object (either from DB or constructed from UISP data)
            if suspension:
                suspension.uisp_service_name = service_data.get('serviceName')
                suspension.uisp_service_status = 'suspended'
                suspension.billing_amount = service_data.get('billingAmount')

                # Add suspension period fields for local records
                suspension_periods = service_data.get('suspensionPeriods', [])
                suspension.suspension_count = len(suspension_periods)
                suspension.latest_suspension_date = None
                suspension.suspension_days = 0

                if suspension_periods:
                    try:
                        latest_suspension = suspension_periods[-1]
                        suspension_start = latest_suspension.get('startDate')
                        if suspension_start:
                            from datetime import datetime
                            dt_aware = datetime.fromisoformat(
                                suspension_start.replace('Z', '+00:00')
                            )
                            # Store as naive UTC (strip timezone info)
                            suspension.latest_suspension_date = dt_aware.replace(tzinfo=None)
                            days_suspended = (datetime.utcnow() - suspension.latest_suspension_date).days
                            suspension.suspension_days = max(0, days_suspended)
                    except Exception as e:
                        logger.warning(f"Error parsing suspension dates for service {service_id}: {str(e)}")

                suspensions_data.append(suspension)
            else:
                # Service is suspended in UISP but no record in our DB
                # Create a pseudo-suspension object for display
                suspensions_data.append(UISPSuspension(service_data, customer))

        # Manual pagination
        per_page = 50
        total = len(suspensions_data)
        start = (page - 1) * per_page
        end = start + per_page
        paginated_data = suspensions_data[start:end]

        class Pagination:
            def __init__(self, page, per_page, total):
                self.page = page
                self.per_page = per_page
                self.total = total
                self.pages = (total + per_page - 1) // per_page if total > 0 else 1
                self.items = []
                self.has_prev = page > 1
                self.has_next = page < self.pages
                self.prev_num = page - 1 if self.has_prev else None
                self.next_num = page + 1 if self.has_next else None

        pagination = Pagination(page, per_page, total)
        pagination.items = paginated_data

        try:
            log_user_activity(
                'VIEW_ACTIVE_SUSPENSIONS',
                f'Viewed active suspensions from UISP. Found {total} suspended services'
            )
        except Exception as e:
            logger.warning(f"Could not log activity: {str(e)}")

        return render_template('suspensions/list.html', suspensions=pagination, filter_type='active')

    except Exception as e:
        logger.error(f'Error fetching active suspensions from UISP: {str(e)}')

        class Pagination:
            def __init__(self):
                self.page = 1
                self.pages = 1
                self.items = []
                self.has_prev = False
                self.has_next = False

        return render_template('suspensions/list.html', suspensions=Pagination(), filter_type='active')


@suspension_bp.route('/candidates', methods=['GET'])
@login_required
def suspension_candidates():
    """List customers who should be suspended based on payment patterns."""
    page = request.args.get('page', 1, type=int)

    # Get all customers
    customers = Customer.query.filter_by(is_active=True).all()
    candidates = []

    # Fetch suspended services from UISP to exclude already suspended customers
    suspended_services = handler.fetch_suspended_services()
    suspended_service_ids = {s.get('id') for s in suspended_services}
    suspended_client_ids = {s.get('clientId') for s in suspended_services}

    for customer in customers:
        # Skip if customer is already suspended in UISP
        if customer.uisp_client_id in suspended_client_ids:
            continue

        should_suspend, reason = handler.should_suspend_service(customer)

        if should_suspend:
            # Check if already suspended
            existing_suspension = Suspension.query.filter_by(
                customer_id=customer.id,
                is_active=True
            ).first()

            if not existing_suspension:
                candidates.append({
                    'customer': customer,
                    'reason': reason,
                    'patterns': PaymentPattern.query.filter_by(customer_id=customer.id).first()
                })

    # Manual pagination
    per_page = 50
    total = len(candidates)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_data = candidates[start:end]

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

    pagination = Pagination(page, per_page, total)

    return render_template('suspensions/candidates.html', candidates=paginated_data, pagination=pagination)


@suspension_bp.route('/customer/<int:customer_id>', methods=['GET'])
@login_required
def customer_suspension_details(customer_id):
    """View suspension details and history for a customer."""
    customer = Customer.query.filter_by(id=customer_id).first()

    if not customer:
        return jsonify({'error': 'Customer not found'}), 404

    # Fetch fresh data from UISP for this customer
    try:
        customer = handler.fetch_and_cache_client(customer.uisp_client_id)
        handler.fetch_and_cache_services(customer)
        handler.fetch_and_cache_invoices(customer)
        handler.fetch_and_cache_payments(customer)
        handler.analyze_payment_pattern(customer)
    except Exception as e:
        logger.warning(f"Could not refresh customer {customer.uisp_client_id} data: {str(e)}")
        # Continue with whatever data we have

    # Get all suspensions for this customer
    suspensions = Suspension.query.filter_by(customer_id=customer_id).order_by(
        Suspension.suspension_date.desc()
    ).all()

    # Get payment pattern
    pattern = PaymentPattern.query.filter_by(customer_id=customer_id).first()

    # Get recent invoices
    invoices = Invoice.query.filter_by(customer_id=customer_id).order_by(
        Invoice.created_date.desc()
    ).limit(10).all()

    # Get services
    services = Service.query.filter_by(customer_id=customer_id).all()

    should_suspend, reason = handler.should_suspend_service(customer)

    return render_template(
        'suspensions/customer_details.html',
        customer=customer,
        suspensions=suspensions,
        pattern=pattern,
        invoices=invoices,
        services=services,
        should_suspend=should_suspend,
        suspension_reason=reason,
        now=datetime.utcnow()
    )


@suspension_bp.route('/api/suspend', methods=['POST'])
@login_required
def api_suspend_service():
    """API endpoint to suspend a service."""
    data = request.get_json()
    customer_id = data.get('customer_id')
    service_id = data.get('service_id')
    reason = data.get('reason', 'Non-payment')
    note = data.get('note', '')
    grace_override = data.get('grace_override', False)

    if not customer_id or not service_id:
        return jsonify({'error': 'customer_id and service_id required'}), 400

    try:
        customer = Customer.query.filter_by(id=customer_id).first()
        service = Service.query.filter_by(
            id=service_id,
            customer_id=customer_id
        ).first()

        if not customer or not service:
            return jsonify({'error': 'Customer or service not found'}), 404

        # Check suspension criteria
        should_suspend, criteria_reason = handler.should_suspend_service(customer, grace_override=grace_override)

        if not should_suspend and not grace_override:
            return jsonify({
                'error': 'Customer does not meet suspension criteria',
                'reason': criteria_reason
            }), 400

        # Suspend in UISP
        uisp_success = handler.suspend_service_uisp(service.uisp_service_id)

        if not uisp_success:
            return jsonify({'error': 'Failed to suspend service in UISP'}), 500

        # Create suspension record
        suspension = Suspension(
            customer_id=customer_id,
            uisp_service_id=service.uisp_service_id,
            suspension_reason=reason,
            suspended_by=current_user.username if current_user else 'api',
            note=note,
            is_active=True
        )

        # Update service status
        service.status = 'suspended'

        db.session.add(suspension)
        db.session.commit()

        # Log audit
        log_user_activity(
            'SUSPEND_SERVICE',
            f'Suspended service {service.uisp_service_id} for customer {customer.uisp_client_id}. Reason: {reason}'
        )

        logger.info(f"Service {service.uisp_service_id} suspended for customer {customer.uisp_client_id} by {current_user.username if current_user else 'api'}")

        return jsonify({
            'status': 'success',
            'message': 'Service suspended successfully',
            'suspension_id': suspension.id
        }), 201

    except Exception as e:
        logger.error(f'Error suspending service: {str(e)}')
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@suspension_bp.route('/api/reactivate', methods=['POST'])
@login_required
def api_reactivate_service():
    """API endpoint to reactivate a suspended service."""
    data = request.get_json()
    suspension_id = data.get('suspension_id')
    note = data.get('note', '')

    if not suspension_id:
        return jsonify({'error': 'suspension_id required'}), 400

    try:
        suspension = Suspension.query.filter_by(id=suspension_id).first()

        if not suspension or not suspension.is_active:
            return jsonify({'error': 'Suspension not found or already resolved'}), 404

        # Reactivate in UISP
        uisp_success = handler.reactivate_service_uisp(suspension.uisp_service_id)

        if not uisp_success:
            return jsonify({'error': 'Failed to reactivate service in UISP'}), 500

        # Update suspension record
        suspension.is_active = False
        suspension.reactivation_date = datetime.now(timezone.utc)
        suspension.reactivated_by = current_user.username if current_user else 'api'
        if note:
            suspension.note = (suspension.note or '') + f'\n[Reactivated] {note}'

        # Update service status
        service = Service.query.filter_by(uisp_service_id=suspension.uisp_service_id).first()
        if service:
            service.status = 'active'

        db.session.commit()

        # Log audit
        log_user_activity(
            'REACTIVATE_SERVICE',
            f'Reactivated service {suspension.uisp_service_id}. Previous reason: {suspension.suspension_reason}'
        )

        logger.info(f"Service {suspension.uisp_service_id} reactivated by {current_user.username if current_user else 'api'}")

        return jsonify({
            'status': 'success',
            'message': 'Service reactivated successfully'
        }), 200

    except Exception as e:
        logger.error(f'Error reactivating service: {str(e)}')
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@suspension_bp.route('/api/bulk_suspend', methods=['POST'])
@login_required
def api_bulk_suspend():
    """API endpoint to suspend multiple services at once."""
    data = request.get_json()
    suspensions = data.get('suspensions', [])

    if not suspensions:
        return jsonify({'error': 'No suspensions provided'}), 400

    results = {
        'success': [],
        'failed': []
    }

    for item in suspensions:
        customer_id = item.get('customer_id')
        service_id = item.get('service_id')
        reason = item.get('reason', 'Bulk suspension - Non-payment')

        try:
            customer = Customer.query.filter_by(id=customer_id).first()
            service = Service.query.filter_by(
                id=service_id,
                customer_id=customer_id
            ).first()

            if not customer or not service:
                results['failed'].append({
                    'customer_id': customer_id,
                    'service_id': service_id,
                    'error': 'Not found'
                })
                continue

            # Suspend in UISP
            uisp_success = handler.suspend_service_uisp(service.uisp_service_id)

            if not uisp_success:
                results['failed'].append({
                    'customer_id': customer_id,
                    'service_id': service_id,
                    'error': 'UISP suspension failed'
                })
                continue

            # Create suspension record
            suspension = Suspension(
                customer_id=customer_id,
                uisp_service_id=service.uisp_service_id,
                suspension_reason=reason,
                suspended_by=current_user.username if current_user else 'api',
                is_active=True
            )

            service.status = 'suspended'
            db.session.add(suspension)

            results['success'].append({
                'customer_id': customer_id,
                'service_id': service_id,
                'suspension_id': suspension.id
            })

        except Exception as e:
            logger.error(f'Error bulk suspending {service_id}: {str(e)}')
            results['failed'].append({
                'customer_id': customer_id,
                'service_id': service_id,
                'error': str(e)
            })

    db.session.commit()

    # Log bulk action
    log_user_activity(
        'BULK_SUSPEND_SERVICES',
        f'Bulk suspended {len(results["success"])} services, {len(results["failed"])} failed'
    )

    return jsonify({
        'status': 'completed',
        'success_count': len(results['success']),
        'failed_count': len(results['failed']),
        'results': results
    }), 200


@suspension_bp.route('/api/refresh_customer/<int:customer_id>', methods=['POST'])
@login_required
def api_refresh_customer_cache(customer_id):
    """Refresh cached data for a customer from UISP."""
    try:
        customer = Customer.query.filter_by(id=customer_id).first()

        if not customer:
            return jsonify({'error': 'Customer not found'}), 404

        # Fetch and cache fresh data
        customer = handler.fetch_and_cache_client(customer.uisp_client_id)
        handler.fetch_and_cache_services(customer)
        handler.fetch_and_cache_invoices(customer)
        handler.fetch_and_cache_payments(customer)
        handler.analyze_payment_pattern(customer)

        log_user_activity(
            'REFRESH_CUSTOMER_CACHE',
            f'Refreshed cached data for customer {customer.uisp_client_id}'
        )

        return jsonify({
            'status': 'success',
            'message': 'Customer cache refreshed',
            'cached_at': customer.cached_at.isoformat()
        }), 200

    except Exception as e:
        logger.error(f'Error refreshing customer cache: {str(e)}')
        return jsonify({'error': str(e)}), 500


@suspension_bp.route('/api/dashboard', methods=['GET'])
@login_required
def api_suspension_dashboard():
    """Get suspension dashboard statistics."""
    try:
        stats = {
            'active_suspensions': Suspension.query.filter_by(is_active=True).count(),
            'resolved_suspensions': Suspension.query.filter(
                Suspension.is_active == False,
                Suspension.reactivation_date != None
            ).count(),
            'vip_customers': Customer.query.filter_by(is_vip=True).count(),
            'customers_with_overdue': Customer.query.filter_by(has_overdue_invoice=True).count(),
            'risky_patterns': PaymentPattern.query.filter_by(is_risky=True).count(),
            'active_services': Service.query.filter_by(status='active').count(),
            'suspended_services': Service.query.filter_by(status='suspended').count(),
        }

        # Get recent suspensions (last 30 days)
        from datetime import timedelta
        recent_date = datetime.utcnow() - timedelta(days=30)
        recent_suspensions = Suspension.query.filter(
            Suspension.suspension_date >= recent_date
        ).count()

        stats['recent_suspensions'] = recent_suspensions

        return jsonify(stats), 200

    except Exception as e:
        logger.error(f'Error getting dashboard stats: {str(e)}')
        return jsonify({'error': str(e)}), 500


@suspension_bp.route('/api/refresh_all_customers', methods=['POST'])
@login_required
def api_refresh_all_customers():
    """Refresh all customers data from UISP.
    This endpoint refreshes all customer data including:
    - Customer basic info (is_active, is_archived, balance, etc.)
    - Services for each customer
    - Invoices for each customer
    - Payment data
    - Payment pattern analysis
    """
    try:
        start_time = datetime.utcnow()

        # Get all customers from database
        customers = Customer.query.all()

        if not customers:
            return jsonify({'error': 'No customers found in database'}), 404

        refresh_count = 0
        error_count = 0

        logger.info(f"Starting refresh of {len(customers)} customers from UISP")

        for customer in customers:
            try:
                # Fetch fresh customer data
                updated_customer = handler.fetch_and_cache_client(customer.uisp_client_id)

                if not updated_customer:
                    error_count += 1
                    logger.warning(f"Could not refresh customer {customer.uisp_client_id}")
                    continue

                # Fetch services, invoices, payments
                handler.fetch_and_cache_services(updated_customer)
                handler.fetch_and_cache_invoices(updated_customer)
                handler.fetch_and_cache_payments(updated_customer)
                handler.analyze_payment_pattern(updated_customer)

                refresh_count += 1

            except Exception as e:
                error_count += 1
                logger.error(f"Error refreshing customer {customer.uisp_client_id}: {str(e)}")
                continue

        end_time = datetime.utcnow()
        elapsed = (end_time - start_time).total_seconds()

        # Log the bulk refresh
        log_user_activity(
            'BULK_REFRESH_CUSTOMERS',
            f'Refreshed {refresh_count}/{len(customers)} customers from UISP ({error_count} errors). Time: {elapsed:.1f}s'
        )

        logger.info(f"Completed refresh: {refresh_count} successful, {error_count} failed in {elapsed:.1f}s")

        return jsonify({
            'status': 'success',
            'message': f'Refreshed {refresh_count}/{len(customers)} customers',
            'refresh_count': refresh_count,
            'error_count': error_count,
            'total_customers': len(customers),
            'elapsed_seconds': elapsed
        }), 200

    except Exception as e:
        logger.error(f'Error refreshing all customers: {str(e)}')
        return jsonify({'error': str(e)}), 500
