"""
UISP Payment Analysis Utilities
"""
import requests
from datetime import datetime, timedelta
from collections import defaultdict
from app.config import Config
from app.models import UISPPayment, Transaction, db
from app.utils import setup_logging

logger = setup_logging('uisp_analyzer')


def fetch_uisp_payments(months=6):
    """
    Fetch payments from UISP API for the specified number of months
    Returns list of payment records
    """
    try:
        url = f"{Config.UISP_BASE_URL}payments"
        headers = {
            Config.UISP_AUTHORIZATION: Config.UISP_API_KEY
        }

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=months * 30)

        params = {
            'createdDateFrom': start_date.strftime('%Y-%m-%d'),
            'createdDateTo': end_date.strftime('%Y-%m-%d'),
            'limit': 1000  # Adjust as needed
        }

        logger.info(f"Fetching UISP payments from {start_date.date()} to {end_date.date()}")

        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        payments = response.json()
        logger.info(f"Fetched {len(payments)} payments from UISP")

        return payments

    except Exception as e:
        logger.error(f"Error fetching UISP payments: {e}")
        return []


def store_uisp_payments(payments):
    """
    Store UISP payments in the database
    """
    new_count = 0
    updated_count = 0

    for payment in payments:
        try:
            payment_id = str(payment.get('id'))
            client_id = payment.get('clientId')
            amount = float(payment.get('amount', 0))
            created_date_str = payment.get('createdDate')

            if not payment_id or not client_id:
                continue

            # Parse created date
            try:
                created_date = datetime.fromisoformat(created_date_str.replace('Z', '+00:00'))
            except:
                created_date = datetime.now()

            # Check if payment already exists
            existing = UISPPayment.query.filter_by(uisp_payment_id=payment_id).first()

            if existing:
                updated_count += 1
            else:
                uisp_payment = UISPPayment(
                    uisp_payment_id=payment_id,
                    client_id=client_id,
                    amount=amount,
                    currency_code=payment.get('currencyCode', 'ZAR'),
                    created_date=created_date,
                    method=payment.get('method', {}).get('name') if isinstance(payment.get('method'), dict) else None,
                    note=payment.get('note'),
                    provider_payment_id=payment.get('providerPaymentId')
                )
                db.session.add(uisp_payment)
                new_count += 1

        except Exception as e:
            logger.error(f"Error storing payment {payment.get('id')}: {e}")

    db.session.commit()
    logger.info(f"Stored {new_count} new payments, {updated_count} already existed")

    return new_count, updated_count


def find_duplicate_payments(days_window=6):
    """
    Find duplicate POSTED payments within a given time window.

    Logic: For each UISP payment, look backwards in time within the window
    to find other payments from the same client with the same amount.

    Example: Payment on Nov 1st looks back 6 days (Oct 26-Nov 1) for duplicates.

    Returns dict of client_id -> list of duplicate groups
    """
    from app.config import Config

    # Use configurable window from .env
    if days_window == 30:
        days_window = Config.DUPLICATE_WINDOW_DAYS  # Use config for 1 month
    elif days_window == 90:
        days_window = Config.DUPLICATE_WINDOW_DAYS * 3  # 3x for 3 months
    elif days_window == 180:
        days_window = Config.DUPLICATE_WINDOW_DAYS * 6  # 6x for 6 months

    duplicates = defaultdict(list)
    processed_pairs = set()  # Track already reported duplicate pairs

    # Get all UISP payments ordered by date (newest first)
    payments = UISPPayment.query.order_by(UISPPayment.created_date.desc()).all()

    # Group by client_id
    by_client = defaultdict(list)
    for payment in payments:
        by_client[payment.client_id].append(payment)

    # Find duplicates for each client
    for client_id, client_payments in by_client.items():
        # Sort by date (newest first)
        client_payments.sort(key=lambda x: x.created_date, reverse=True)

        for payment in client_payments:
            # Look backwards in time within the window
            window_start = payment.created_date - timedelta(days=days_window)

            matches = []
            for other in client_payments:
                # Skip self
                if other.id == payment.id:
                    continue

                # Check if other payment is within the lookback window
                # and is before or on the same day as current payment
                if (other.created_date < payment.created_date and
                    other.created_date >= window_start):

                    # Check if same amount (within 1 cent tolerance)
                    if abs(other.amount - payment.amount) < 0.01:
                        # Create unique pair ID to avoid duplicates
                        pair_id = tuple(sorted([payment.id, other.id]))

                        if pair_id not in processed_pairs:
                            matches.append(other)
                            processed_pairs.add(pair_id)

            if matches:
                # Calculate days between payments
                for match in matches:
                    days_apart = (payment.created_date - match.created_date).days

                duplicates[client_id].append({
                    'payment': payment,
                    'matches': matches,
                    'count': len(matches) + 1,
                    'amount': payment.amount,
                    'days_apart': [(payment.created_date - m.created_date).days for m in matches]
                })

    return duplicates


def analyze_incorrect_references():
    """
    Find customers who frequently use incorrect payment references
    (i.e., transactions where original_reference differs from what was extracted)
    """
    incorrect_refs = defaultdict(list)

    # Get transactions where CID was changed
    transactions = Transaction.query.filter(
        Transaction.CID != Transaction.original_CID,
        Transaction.CID != 'unallocated'
    ).all()

    for txn in transactions:
        incorrect_refs[txn.CID].append({
            'entryId': txn.entryId,
            'amount': txn.amount,
            'valueDate': txn.valueDate,
            'original_reference': txn.original_reference,
            'corrected_reference': txn.reference,
            'original_remittance_info': txn.original_remittance_info,
            'original_CID': txn.original_CID,
            'corrected_CID': txn.CID,
            'posted': txn.posted
        })

    # Sort by frequency (customers with most errors first)
    sorted_refs = dict(sorted(incorrect_refs.items(), key=lambda x: len(x[1]), reverse=True))

    return sorted_refs


def get_duplicate_analysis_summary(months=6):
    """
    Get comprehensive duplicate analysis
    """
    duplicates_1month = find_duplicate_payments(30)
    duplicates_3months = find_duplicate_payments(90)
    duplicates_6months = find_duplicate_payments(180)

    summary = {
        '1_month': {
            'clients_affected': len(duplicates_1month),
            'total_duplicates': sum(len(d) for d in duplicates_1month.values()),
            'details': duplicates_1month
        },
        '3_months': {
            'clients_affected': len(duplicates_3months),
            'total_duplicates': sum(len(d) for d in duplicates_3months.values()),
            'details': duplicates_3months
        },
        '6_months': {
            'clients_affected': len(duplicates_6months),
            'total_duplicates': sum(len(d) for d in duplicates_6months.values()),
            'details': duplicates_6months
        }
    }

    return summary
