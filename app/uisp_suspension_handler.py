"""
UISP API handler for suspension feature.
Manages caching and efficient data fetching for suspension analysis.
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from app import db
from app.models import Customer, Service, Invoice, CachedPayment, PaymentPattern
from app.config import Config

logger = logging.getLogger(__name__)


class UISPSuspensionHandler:
    """Handles UISP API interactions for suspension management."""

    # Use base API URL without version - endpoints include their own version
    BASE_URL = "https://uisp-ros1.afrieta.com/crm/api/"
    API_KEY = Config.UISP_API_KEY
    CACHE_DURATION_HOURS = 24  # Cache customer data for 24 hours
    LOOKBACK_DAYS = 180  # Analyze last 6 months of payment history

    def __init__(self):
        self.headers = {
            'X-Auth-App-Key': self.API_KEY,
            'Content-Type': 'application/json'
        }

    def _make_request(self, method: str, endpoint: str, params=None, data=None) -> Optional[dict]:
        """Make authenticated request to UISP API."""
        url = f"{self.BASE_URL}{endpoint}"
        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers, params=params, timeout=30)
            elif method == 'PATCH':
                response = requests.patch(url, headers=self.headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            return response.json() if response.text else None

        except requests.exceptions.RequestException as e:
            logger.error(f"UISP API request failed: {method} {endpoint} - {str(e)}")
            return None

    def fetch_and_cache_client(self, client_id: int) -> Optional[Customer]:
        """Fetch client from UISP and cache locally. Returns None if fetch fails."""
        try:
            # Fetch from UISP
            endpoint = f"v2.1/clients/{client_id}"
            client_data = self._make_request('GET', endpoint)

            if not client_data:
                logger.warning(f"Failed to fetch client {client_id} from UISP")
                return None

            # Extract VIP and grace payment date from attributes
            is_vip = False
            grace_payment_date = None

            if 'attributes' in client_data:
                for attr in client_data['attributes']:
                    if attr.get('key') == 'vip':
                        is_vip = attr.get('value', '0') == '1'
                    elif attr.get('key') == 'gracePaymentDate':
                        try:
                            grace_payment_date = int(attr.get('value', 0))
                        except (ValueError, TypeError):
                            grace_payment_date = None

            # Check if customer exists locally
            customer = Customer.query.filter_by(uisp_client_id=client_id).first()

            if not customer:
                customer = Customer(uisp_client_id=client_id)
                db.session.add(customer)

            # Update customer data
            customer.first_name = client_data.get('firstName')
            customer.last_name = client_data.get('lastName')
            customer.email = client_data.get('username')
            customer.is_vip = is_vip
            customer.is_archived = client_data.get('isArchived', False)
            customer.grace_payment_date = grace_payment_date
            customer.account_balance = client_data.get('accountBalance', 0.0)
            customer.account_outstanding = client_data.get('accountOutstanding', 0.0)
            customer.account_credit = client_data.get('accountCredit', 0.0)
            customer.is_active = client_data.get('isActive', True)
            customer.has_overdue_invoice = client_data.get('hasOverdueInvoice', False)
            customer.cached_at = datetime.utcnow()

            # Extract address
            if client_data.get('fullAddress'):
                customer.address = client_data.get('fullAddress')

            # Extract contact info
            if 'contacts' in client_data:
                for contact in client_data['contacts']:
                    if contact.get('isBilling'):
                        customer.phone = contact.get('phone')
                        break

            db.session.commit()
            logger.info(f"Cached customer {client_id} in database")
            return customer

        except Exception as e:
            logger.error(f"Error caching client {client_id}: {str(e)}")
            db.session.rollback()
            return None

    def fetch_and_cache_services(self, customer: Customer) -> List[Service]:
        """Fetch all services for customer (active and suspended) and cache locally."""
        try:
            client_id = customer.uisp_client_id
            endpoint = "v2.0/clients/services"
            params = {
                'clientId': client_id
                # Don't filter by status - get all services (active, suspended, etc.)
            }

            services_data = self._make_request('GET', endpoint, params=params)

            if not services_data:
                logger.warning(f"No services found for client {client_id}")
                return []

            # Handle both list and dict responses
            if isinstance(services_data, dict) and 'data' in services_data:
                services_list = services_data['data']
            elif isinstance(services_data, list):
                services_list = services_data
            else:
                logger.error(f"Unexpected UISP services response format: {type(services_data)}")
                return []

            cached_services = []

            for service_data in services_list:
                service_id = service_data.get('id')

                # Check if service already cached
                service = Service.query.filter_by(uisp_service_id=service_id).first()

                if not service:
                    service = Service(customer_id=customer.id, uisp_service_id=service_id)
                    db.session.add(service)

                # Update service data - use 'name' field (not 'serviceName')
                service.service_name = service_data.get('name') or service_data.get('serviceName')
                service.status = self._map_service_status(service_data.get('status'))
                # Use 'price' field (not 'billingAmount')
                service.billing_amount = service_data.get('price') or service_data.get('billingAmount')
                service.cached_at = datetime.utcnow()

                # Extract suspension period data
                suspension_periods = service_data.get('suspensionPeriods', [])
                service.suspension_count = len(suspension_periods)

                # Get the most recent suspension (last in the list)
                if suspension_periods:
                    latest_suspension = suspension_periods[-1]
                    suspension_start = latest_suspension.get('startDate')

                    if suspension_start:
                        # Parse ISO format date string
                        try:
                            service.latest_suspension_date = datetime.fromisoformat(suspension_start.replace('Z', '+00:00'))
                            # Calculate days suspended
                            days_suspended = (datetime.utcnow() - service.latest_suspension_date).days
                            service.suspension_days = max(0, days_suspended)
                        except (ValueError, AttributeError) as e:
                            logger.warning(f"Could not parse suspension date {suspension_start}: {e}")

                cached_services.append(service)

            db.session.commit()
            logger.info(f"Cached {len(cached_services)} services for customer {client_id}")
            return cached_services

        except Exception as e:
            logger.error(f"Error caching services for customer {customer.id}: {str(e)}")
            db.session.rollback()
            return []

    def fetch_and_cache_invoices(self, customer: Customer) -> List[Invoice]:
        """Fetch last 6 months of invoices for customer and cache locally."""
        try:
            client_id = customer.uisp_client_id
            endpoint = "v1.0/invoices"

            # Calculate date range (last 6 months)
            to_date = datetime.utcnow()
            from_date = to_date - timedelta(days=self.LOOKBACK_DAYS)

            params = {
                'clientId': client_id,
                'createdDateFrom': from_date.strftime('%Y-%m-%d'),
                'createdDateTo': to_date.strftime('%Y-%m-%d'),
                'limit': 1000
            }

            invoices_data = self._make_request('GET', endpoint, params=params)

            if not invoices_data:
                logger.warning(f"No invoices found for client {client_id}")
                return []

            # Handle both list and dict responses
            if isinstance(invoices_data, dict) and 'data' in invoices_data:
                invoices_list = invoices_data['data']
            elif isinstance(invoices_data, list):
                invoices_list = invoices_data
            else:
                logger.error(f"Unexpected UISP invoices response format: {type(invoices_data)}")
                return []

            cached_invoices = []

            for invoice_data in invoices_list:
                invoice_id = invoice_data.get('id')

                # Check if invoice already cached
                invoice = Invoice.query.filter_by(uisp_invoice_id=invoice_id).first()

                if not invoice:
                    invoice = Invoice(customer_id=customer.id, uisp_invoice_id=invoice_id)
                    db.session.add(invoice)

                # Update invoice data - use correct field names from UISP API
                invoice.invoice_number = invoice_data.get('number') or invoice_data.get('invoiceNumber')

                # Use 'total' field directly, or calculate from items if not available
                invoice.total_amount = invoice_data.get('total') or invoice_data.get('totalAmount', 0.0)

                # Use 'amountToPay' as remaining amount (what still needs to be paid)
                invoice.remaining_amount = invoice_data.get('amountToPay') or invoice_data.get('remainingAmount', 0.0)

                # Map invoice status
                status_key = invoice_data.get('status') or invoice_data.get('invoiceStatus')
                invoice.status = self._map_invoice_status(status_key)

                # Parse dates
                created = invoice_data.get('createdDate')
                due = invoice_data.get('dueDate')
                invoice.created_date = datetime.fromisoformat(created.replace('Z', '+00:00')) if created else None
                invoice.due_date = datetime.fromisoformat(due.replace('Z', '+00:00')) if due else None

                invoice.cached_at = datetime.utcnow()
                cached_invoices.append(invoice)

            db.session.commit()
            logger.info(f"Cached {len(cached_invoices)} invoices for customer {client_id}")
            return cached_invoices

        except Exception as e:
            logger.error(f"Error caching invoices for customer {customer.id}: {str(e)}")
            db.session.rollback()
            return []

    def fetch_and_cache_payments(self, customer: Customer) -> List[CachedPayment]:
        """Fetch last 6 months of payments for customer and cache locally."""
        try:
            client_id = customer.uisp_client_id
            endpoint = "v1.0/payments"

            # Calculate date range (last 6 months)
            to_date = datetime.utcnow()
            from_date = to_date - timedelta(days=self.LOOKBACK_DAYS)

            params = {
                'clientId': client_id,
                'createdDateFrom': from_date.strftime('%Y-%m-%d'),
                'createdDateTo': to_date.strftime('%Y-%m-%d'),
                'limit': 1000
            }

            payments_data = self._make_request('GET', endpoint, params=params)

            if not payments_data:
                logger.warning(f"No payments found for client {client_id}")
                return []

            # Handle both list and dict responses
            if isinstance(payments_data, dict) and 'data' in payments_data:
                payments_list = payments_data['data']
            elif isinstance(payments_data, list):
                payments_list = payments_data
            else:
                logger.error(f"Unexpected UISP payments response format: {type(payments_data)}")
                return []

            cached_payments = []

            for payment_data in payments_list:
                payment_id = payment_data.get('id')

                # Check if payment already cached
                payment = CachedPayment.query.filter_by(uisp_payment_id=str(payment_id)).first()

                if not payment:
                    payment = CachedPayment(
                        customer_id=customer.id,
                        uisp_payment_id=str(payment_id)
                    )
                    db.session.add(payment)

                # Update payment data
                payment.amount = payment_data.get('amount', 0.0)
                payment.method = payment_data.get('method', {}).get('name') if isinstance(payment_data.get('method'), dict) else None
                payment.note = payment_data.get('note')

                # Parse date
                created = payment_data.get('createdDate')
                if created:
                    payment.created_date = datetime.fromisoformat(created.replace('Z', '+00:00'))

                payment.cached_at = datetime.utcnow()
                cached_payments.append(payment)

            db.session.commit()
            logger.info(f"Cached {len(cached_payments)} payments for customer {client_id}")
            return cached_payments

        except Exception as e:
            logger.error(f"Error caching payments for customer {customer.id}: {str(e)}")
            db.session.rollback()
            return []

    def analyze_payment_pattern(self, customer: Customer) -> Optional[PaymentPattern]:
        """Analyze customer's payment pattern based on cached data."""
        try:
            invoices = Invoice.query.filter_by(customer_id=customer.id).all()
            payments = CachedPayment.query.filter_by(customer_id=customer.id).all()

            if not invoices or not payments:
                logger.warning(f"Insufficient data to analyze pattern for customer {customer.id}")
                return None

            # Create or update pattern record
            pattern = PaymentPattern.query.filter_by(customer_id=customer.id).first()
            if not pattern:
                pattern = PaymentPattern(customer_id=customer.id)
                db.session.add(pattern)

            # Calculate metrics
            total_paid = sum(p.amount for p in payments)
            total_invoiced = sum(i.total_amount for i in invoices if i.status != 'cancelled')

            if total_invoiced > 0:
                pattern.avg_payment_amount = total_paid / len(payments) if payments else 0

            # Count late/missed payments
            # Use remaining_amount to determine if invoice is truly paid (not just status field)
            pattern.late_payment_count = 0
            pattern.on_time_payment_count = 0
            pattern.missed_payment_count = 0
            total_days_late = 0

            for invoice in invoices:
                # Invoice is paid if remaining_amount is 0
                is_paid = invoice.remaining_amount == 0 or invoice.remaining_amount is None

                if is_paid and invoice.due_date:
                    # Invoice was paid - check if on time or late
                    # Get most recent payment date for this invoice (if we had individual payment matching)
                    # For now, assume paid on time if any payment exists before or on due date
                    if payments:
                        # Check if any payment was on or before due date
                        on_time_payments = [p for p in payments if p.created_date and p.created_date <= invoice.due_date]
                        if on_time_payments:
                            pattern.on_time_payment_count += 1
                        else:
                            # All payments were after due date = late
                            pattern.late_payment_count += 1
                            # Calculate days late (from due date to last payment)
                            latest_payment = max((p.created_date for p in payments if p.created_date), default=None)
                            if latest_payment:
                                days_late = (latest_payment - invoice.due_date).days
                                total_days_late += days_late
                    else:
                        # Paid but no payment records (assume on time)
                        pattern.on_time_payment_count += 1

                elif not is_paid and invoice.due_date:
                    # Invoice is unpaid and has passed due date
                    if invoice.due_date < datetime.utcnow():
                        pattern.missed_payment_count += 1

            if pattern.late_payment_count > 0:
                pattern.avg_days_late = total_days_late / pattern.late_payment_count

            # Determine if risky
            pattern.is_risky = (
                pattern.missed_payment_count >= 2 or
                pattern.late_payment_count >= 3 or
                (pattern.avg_days_late and pattern.avg_days_late > 30)
            )

            pattern.last_payment_date = max((p.created_date for p in payments), default=None)
            pattern.analysis_period_start = datetime.utcnow() - timedelta(days=self.LOOKBACK_DAYS)
            pattern.analysis_period_end = datetime.utcnow()
            pattern.calculated_at = datetime.utcnow()

            db.session.commit()
            logger.info(f"Analyzed payment pattern for customer {customer.id}: risky={pattern.is_risky}")
            return pattern

        except Exception as e:
            logger.error(f"Error analyzing payment pattern for customer {customer.id}: {str(e)}")
            db.session.rollback()
            return None

    def should_suspend_service(self, customer: Customer, grace_override: bool = False) -> tuple[bool, str]:
        """
        Determine if service should be suspended.
        Returns: (should_suspend: bool, reason: str)
        """
        # Check VIP status
        if customer.is_vip:
            return False, "Customer is VIP"

        # Check grace payment date
        if customer.grace_payment_date and not grace_override:
            today = datetime.now().day
            if today <= customer.grace_payment_date:
                return False, f"Within grace period (due by {customer.grace_payment_date}th)"

        # Check for overdue invoices
        if customer.has_overdue_invoice:
            overdue_invoices = Invoice.query.filter(
                Invoice.customer_id == customer.id,
                Invoice.status.in_(['unpaid', 'overdue']),
                Invoice.due_date < datetime.utcnow()
            ).all()

            if overdue_invoices:
                return True, f"{len(overdue_invoices)} overdue invoice(s)"

        # Check payment pattern
        pattern = PaymentPattern.query.filter_by(customer_id=customer.id).first()
        if pattern and pattern.is_risky:
            if pattern.missed_payment_count >= 2:
                return True, f"{pattern.missed_payment_count} missed payment(s)"
            if pattern.late_payment_count >= 3:
                return True, f"{pattern.late_payment_count} late payment(s)"

        return False, "No suspension criteria met"

    def suspend_service_uisp(self, service_id: int) -> bool:
        """Call UISP API to suspend a service."""
        try:
            endpoint = f"v2.0/services/{service_id}"
            data = {'status': '3'}  # 3 = suspended status in UISP

            result = self._make_request('PATCH', endpoint, data=data)

            if result:
                logger.info(f"Successfully suspended service {service_id} in UISP")
                return True
            else:
                logger.error(f"Failed to suspend service {service_id} in UISP")
                return False

        except Exception as e:
            logger.error(f"Error suspending service {service_id} in UISP: {str(e)}")
            return False

    def reactivate_service_uisp(self, service_id: int) -> bool:
        """Call UISP API to reactivate a service."""
        try:
            endpoint = f"v2.0/services/{service_id}"
            data = {'status': '1'}  # 1 = active status in UISP

            result = self._make_request('PATCH', endpoint, data=data)

            if result:
                logger.info(f"Successfully reactivated service {service_id} in UISP")
                return True
            else:
                logger.error(f"Failed to reactivate service {service_id} in UISP")
                return False

        except Exception as e:
            logger.error(f"Error reactivating service {service_id} in UISP: {str(e)}")
            return False

    def fetch_suspended_services(self) -> List[Dict]:
        """Fetch all suspended services (status=3) from UISP for all customers."""
        try:
            endpoint = "v1.0/clients/services"
            params = {
                'statuses[]': '3'  # 3 = suspended status
            }

            services_data = self._make_request('GET', endpoint, params=params)

            if not services_data:
                logger.warning("No suspended services found in UISP")
                return []

            # Handle both list and dict responses
            if isinstance(services_data, dict) and 'data' in services_data:
                services_list = services_data['data']
            elif isinstance(services_data, list):
                services_list = services_data
            else:
                logger.error(f"Unexpected UISP suspended services response format: {type(services_data)}")
                return []

            logger.info(f"Fetched {len(services_list)} suspended services from UISP")
            return services_list

        except Exception as e:
            logger.error(f"Error fetching suspended services from UISP: {str(e)}")
            return []

    def _map_service_status(self, uisp_status: int) -> str:
        """Map UISP service status code to readable status."""
        status_map = {
            1: 'active',
            2: 'prepared',
            3: 'suspended',
            4: 'quoted',
        }
        return status_map.get(uisp_status, 'unknown')

    def _map_invoice_status(self, uisp_status) -> str:
        """Map UISP invoice status to readable status.
        UISP returns numeric status codes:
        1=issued/unpaid, 2=paid, 3=paid
        Mapping is based on amountToPay (use remaining_amount instead)
        """
        if uisp_status is None:
            return 'unknown'

        # Convert to string for dictionary lookup
        status_str = str(uisp_status).lower()

        # Handle numeric statuses - based on actual UISP behavior
        # Status 1: issued/unpaid (amountToPay > 0)
        # Status 3: paid (amountToPay = 0)
        status_map = {
            '1': 'unpaid',      # Issued but not paid
            '2': 'paid',        # Paid
            '3': 'paid',        # Paid (confirmed by amountToPay=0)
            # Also handle string versions
            'draft': 'draft',
            'issued': 'issued',
            'unpaid': 'unpaid',
            'overdue': 'overdue',
            'paid': 'paid',
            'cancelled': 'cancelled',
        }
        return status_map.get(status_str, 'unknown')
