from app import db
from datetime import datetime
from sqlalchemy import Index
from flask_login import UserMixin

class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    entryId = db.Column(db.String(255), unique=True, nullable=False, index=True)
    account = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    valueDate = db.Column(db.String(10), nullable=True)
    remittance_info = db.Column(db.Text, nullable=True)
    reference = db.Column(db.Text, nullable=True)
    CID = db.Column(db.String(50), default='unallocated')
    posted = db.Column(db.String(10), default='no')
    UISPpaymentId = db.Column(db.String(255), nullable=True)
    postedDate = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default='pending')
    note = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(50), default='FNB-PAYMENT')

    # Original data from FNB (before any modifications)
    original_reference = db.Column(db.Text, nullable=True)
    original_remittance_info = db.Column(db.Text, nullable=True)
    original_CID = db.Column(db.String(50), nullable=True)

    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_timestamp_posted', 'timestamp', 'posted'),
        Index('idx_cid_posted', 'CID', 'posted'),
    )

    def __repr__(self):
        return f'<Transaction {self.entryId}>'


class FailedTransaction(db.Model):
    __tablename__ = 'failed_transactions'

    id = db.Column(db.Integer, primary_key=True)
    entryId = db.Column(db.String(255), db.ForeignKey('transactions.entryId'), nullable=False, index=True)
    reason = db.Column(db.Text, nullable=True)
    manual_cid = db.Column(db.String(50), nullable=True)
    error_code = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved = db.Column(db.Boolean, default=False)
    resolved_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<FailedTransaction {self.entryId}>'


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    entryId = db.Column(db.String(255), db.ForeignKey('transactions.entryId'), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    field_name = db.Column(db.String(100), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    changed_by = db.Column(db.String(100), default='system')

    def __repr__(self):
        return f'<AuditLog {self.entryId} - {self.action}>'


class ExecutionLog(db.Model):
    __tablename__ = 'execution_logs'

    id = db.Column(db.Integer, primary_key=True)
    script_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=True)
    transactions_processed = db.Column(db.Integer, default=0)
    transactions_failed = db.Column(db.Integer, default=0)
    total_amount = db.Column(db.Float, default=0.0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f'<ExecutionLog {self.script_name} - {self.status}>'


class UISPPayment(db.Model):
    __tablename__ = 'uisp_payments'

    id = db.Column(db.Integer, primary_key=True)
    uisp_payment_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    client_id = db.Column(db.Integer, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    currency_code = db.Column(db.String(10), default='ZAR')
    created_date = db.Column(db.DateTime, nullable=False, index=True)
    method = db.Column(db.String(100), nullable=True)
    note = db.Column(db.Text, nullable=True)
    provider_payment_id = db.Column(db.String(255), nullable=True)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('idx_client_created', 'client_id', 'created_date'),
        Index('idx_amount_created', 'amount', 'created_date'),
    )

    def __repr__(self):
        return f'<UISPPayment {self.uisp_payment_id} - Client {self.client_id}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    role = db.Column(db.String(20), default='user', nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    must_change_password = db.Column(db.Boolean, default=True, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.String(80), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.username}>'


class UserActivityLog(db.Model):
    __tablename__ = 'user_activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    username = db.Column(db.String(80), nullable=False, index=True)
    action_type = db.Column(db.String(50), nullable=False)
    action_description = db.Column(db.String(500), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    endpoint = db.Column(db.String(200), nullable=True)
    method = db.Column(db.String(10), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index('idx_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_action_timestamp', 'action_type', 'timestamp'),
    )

    def __repr__(self):
        return f'<UserActivityLog {self.username} - {self.action_type}>'


class Customer(db.Model):
    __tablename__ = 'customers'

    id = db.Column(db.Integer, primary_key=True)
    uisp_client_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    first_name = db.Column(db.String(120), nullable=True)
    last_name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), nullable=True, index=True)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    is_vip = db.Column(db.Boolean, default=False, index=True)
    is_archived = db.Column(db.Boolean, default=False, index=True)
    grace_payment_date = db.Column(db.Integer, nullable=True)
    account_balance = db.Column(db.Float, default=0.0)
    account_outstanding = db.Column(db.Float, default=0.0)
    account_credit = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True, index=True)
    has_overdue_invoice = db.Column(db.Boolean, default=False)
    cached_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    services = db.relationship('Service', backref='customer', lazy=True, cascade='all, delete-orphan')
    invoices = db.relationship('Invoice', backref='customer', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('CachedPayment', backref='customer', lazy=True, cascade='all, delete-orphan')
    suspensions = db.relationship('Suspension', backref='customer', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Customer {self.uisp_client_id} - {self.first_name} {self.last_name}>'


class Service(db.Model):
    __tablename__ = 'services'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    uisp_service_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    service_name = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), default='active', index=True)  # active, suspended, prepared, quoted
    billing_amount = db.Column(db.Float, nullable=True)
    billing_period_start = db.Column(db.DateTime, nullable=True)
    billing_period_end = db.Column(db.DateTime, nullable=True)
    suspension_count = db.Column(db.Integer, default=0)  # Total number of suspension periods
    latest_suspension_date = db.Column(db.DateTime, nullable=True)  # Most recent suspension start date
    suspension_days = db.Column(db.Integer, default=0)  # Days suspended (calculated from latest suspension)
    cached_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Service {self.uisp_service_id} - {self.service_name}>'


class Invoice(db.Model):
    __tablename__ = 'invoices'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    uisp_invoice_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    invoice_number = db.Column(db.String(50), nullable=True, index=True)
    total_amount = db.Column(db.Float, nullable=False)
    remaining_amount = db.Column(db.Float, nullable=False)
    created_date = db.Column(db.DateTime, nullable=False, index=True)
    due_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default='unpaid', index=True)  # draft, issued, unpaid, overdue, paid, cancelled
    cached_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_customer_created', 'customer_id', 'created_date'),
        Index('idx_customer_status', 'customer_id', 'status'),
    )

    def __repr__(self):
        return f'<Invoice {self.invoice_number}>'


class CachedPayment(db.Model):
    __tablename__ = 'cached_payments'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    uisp_payment_id = db.Column(db.String(255), nullable=False, unique=True, index=True)
    amount = db.Column(db.Float, nullable=False)
    created_date = db.Column(db.DateTime, nullable=False, index=True)
    method = db.Column(db.String(100), nullable=True)
    note = db.Column(db.Text, nullable=True)
    cached_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_customer_created', 'customer_id', 'created_date'),
    )

    def __repr__(self):
        return f'<CachedPayment {self.uisp_payment_id}>'


class Suspension(db.Model):
    __tablename__ = 'suspensions'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    uisp_service_id = db.Column(db.Integer, nullable=False, index=True)
    suspension_reason = db.Column(db.String(255), nullable=True)
    suspension_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    suspended_by = db.Column(db.String(80), default='system')
    reactivation_date = db.Column(db.DateTime, nullable=True)
    reactivated_by = db.Column(db.String(80), nullable=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_customer_active', 'customer_id', 'is_active'),
        Index('idx_service_active', 'uisp_service_id', 'is_active'),
    )

    def __repr__(self):
        return f'<Suspension {self.uisp_service_id} - {self.suspension_reason}>'


class PaymentPattern(db.Model):
    __tablename__ = 'payment_patterns'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, unique=True, index=True)
    avg_payment_amount = db.Column(db.Float, nullable=True)
    avg_days_late = db.Column(db.Float, nullable=True)
    missed_payment_count = db.Column(db.Integer, default=0)
    late_payment_count = db.Column(db.Integer, default=0)
    on_time_payment_count = db.Column(db.Integer, default=0)
    last_payment_date = db.Column(db.DateTime, nullable=True)
    analysis_period_start = db.Column(db.DateTime, default=datetime.utcnow)
    analysis_period_end = db.Column(db.DateTime, default=datetime.utcnow)
    is_risky = db.Column(db.Boolean, default=False, index=True)
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<PaymentPattern Customer {self.customer_id}>'
