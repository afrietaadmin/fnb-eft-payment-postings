"""
Authentication routes for user login, logout, and management
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, current_user, login_required
from datetime import datetime, timezone
from app import db, limiter
from app.models import User, UserActivityLog, Customer
from app.auth import hash_password, check_password, generate_random_password, admin_required
from app.uisp_suspension_handler import UISPSuspensionHandler
import logging

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def log_activity(action_type, action_description=None, endpoint=None, method=None):
    """Log user activity"""
    try:
        log = UserActivityLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            username=current_user.username if current_user.is_authenticated else 'anonymous',
            action_type=action_type,
            action_description=action_description,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string[:500] if request.user_agent else None,
            endpoint=endpoint or request.endpoint,
            method=method or request.method,
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error logging activity: {e}")

@auth_bp.route('/login', methods=['GET'])
def login_page():
    """Display login page"""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    return render_template('login.html')

@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    """Process login"""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    remember = request.form.get('remember', False)

    if not username or not password:
        flash('Username and password are required', 'error')
        log_activity('login_attempt_failed', 'Missing credentials', endpoint='auth.login', method='POST')
        return redirect(url_for('auth.login_page'))

    user = User.query.filter_by(username=username).first()

    if not user or not check_password(user.password_hash, password):
        flash('Invalid username or password', 'error')
        log_activity('login_attempt_failed', f'Invalid credentials for user: {username}', endpoint='auth.login', method='POST')
        return redirect(url_for('auth.login_page'))

    if not user.is_active:
        flash('Account is inactive', 'error')
        log_activity('login_attempt_failed', f'Inactive account: {username}', endpoint='auth.login', method='POST')
        return redirect(url_for('auth.login_page'))

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.session.commit()

    login_user(user, remember=remember)
    session.permanent = True
    log_activity('login_success', f'User logged in', endpoint='auth.login', method='POST')

    # Refresh UISP data in background (non-blocking)
    logger.info(f"=== Starting UISP data sync for user {user.username} ===")
    try:
        handler = UISPSuspensionHandler()
        customers = Customer.query.all()
        refresh_count = 0
        logger.info(f"Found {len(customers)} customers to sync")

        for customer in customers:
            try:
                logger.info(f"Syncing customer {customer.id}: {customer.first_name} {customer.last_name} (UISP: {customer.uisp_client_id})")
                updated_customer = handler.fetch_and_cache_client(customer.uisp_client_id)
                if updated_customer:
                    handler.fetch_and_cache_services(updated_customer)
                    handler.fetch_and_cache_invoices(updated_customer)
                    handler.fetch_and_cache_payments(updated_customer)
                    handler.analyze_payment_pattern(updated_customer)
                    refresh_count += 1
                    logger.info(f"Successfully synced customer {customer.id}")
            except Exception as e:
                logger.warning(f"Error refreshing customer {customer.uisp_client_id} on login: {str(e)}")
                continue

        logger.info(f"=== UISP sync complete: Refreshed {refresh_count}/{len(customers)} customers ===")
        # Store sync info in session for frontend notification
        session['login_sync_success'] = True
        session['login_sync_count'] = refresh_count
        session['login_sync_total'] = len(customers)
        session.modified = True
        logger.info(f"Session set: login_sync_success=True, count={refresh_count}, total={len(customers)}")

    except Exception as e:
        logger.error(f"=== UISP sync failed ===: {str(e)}", exc_info=True)
        # Don't block login if refresh fails
        session['login_sync_error'] = True
        session.modified = True
        logger.warning(f"Session set: login_sync_error=True")

    # Check if password change is required
    if user.must_change_password:
        flash('You must change your password on first login', 'warning')
        return redirect(url_for('auth.change_password_page'))

    return redirect(request.args.get('next', url_for('main.index')))

@auth_bp.route('/logout', methods=['GET'])
@login_required
def logout():
    """Logout user"""
    username = current_user.username
    logout_user()
    log_activity('logout', f'User logged out', endpoint='auth.logout', method='GET')
    flash('You have been logged out', 'info')
    return redirect(url_for('auth.login_page'))

@auth_bp.route('/change-password', methods=['GET'])
@login_required
def change_password_page():
    """Display change password page"""
    return render_template('change_password.html', first_login=current_user.must_change_password)

@auth_bp.route('/change-password', methods=['POST'])
@login_required
@limiter.limit("10 per hour")
def change_password():
    """Process password change"""
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    # Only check current password if not first login
    if not current_user.must_change_password:
        if not current_password:
            flash('Current password is required', 'error')
            return redirect(url_for('auth.change_password_page'))

        if not check_password(current_user.password_hash, current_password):
            flash('Current password is incorrect', 'error')
            log_activity('password_change_failed', 'Invalid current password', endpoint='auth.change_password', method='POST')
            return redirect(url_for('auth.change_password_page'))

    if not new_password or not confirm_password:
        flash('New password and confirmation are required', 'error')
        return redirect(url_for('auth.change_password_page'))

    if new_password != confirm_password:
        flash('New passwords do not match', 'error')
        return redirect(url_for('auth.change_password_page'))

    if len(new_password) < 8:
        flash('Password must be at least 8 characters', 'error')
        return redirect(url_for('auth.change_password_page'))

    # Update password
    current_user.password_hash = hash_password(new_password)
    current_user.must_change_password = False
    db.session.commit()

    log_activity('password_changed', 'User changed their password', endpoint='auth.change_password', method='POST')
    flash('Password changed successfully', 'success')
    return redirect(url_for('main.index'))

# Admin routes

@auth_bp.route('/admin/users', methods=['GET'])
@admin_required
def users_page():
    """Display user management page"""
    users = User.query.order_by(User.username).all()
    return render_template('admin/users.html', users=users)

@auth_bp.route('/admin/users/create', methods=['POST'])
@admin_required
def create_user():
    """Create new user"""
    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', 'user')

    if not username:
        flash('Username is required', 'error')
        log_activity('user_create_failed', 'Missing username', endpoint='auth.create_user', method='POST')
        return redirect(url_for('auth.users_page'))

    if User.query.filter_by(username=username).first():
        flash('Username already exists', 'error')
        log_activity('user_create_failed', f'Username already exists: {username}', endpoint='auth.create_user', method='POST')
        return redirect(url_for('auth.users_page'))

    # Generate random password
    temp_password = generate_random_password()
    password_hash = hash_password(temp_password)

    user = User(
        username=username,
        password_hash=password_hash,
        full_name=full_name,
        role=role,
        is_active=True,
        must_change_password=True,
        created_by=current_user.username,
        created_at=datetime.now(timezone.utc)
    )
    db.session.add(user)
    db.session.commit()

    log_activity('user_created', f'Admin created user: {username}', endpoint='auth.create_user', method='POST')
    flash(f'User {username} created. Temporary password: {temp_password}', 'success')
    return redirect(url_for('auth.users_page'))

@auth_bp.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
@limiter.limit("10 per hour")
def reset_password(user_id):
    """Reset user password"""
    user = User.query.get(user_id)
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('auth.users_page'))

    temp_password = generate_random_password()
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    db.session.commit()

    log_activity('user_password_reset', f'Admin reset password for user: {user.username}', endpoint='auth.reset_password', method='POST')
    flash(f'Password reset for {user.username}. New temporary password: {temp_password}', 'success')
    return redirect(url_for('auth.users_page'))

@auth_bp.route('/admin/users/<int:user_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_active(user_id):
    """Toggle user active status"""
    user = User.query.get(user_id)
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('auth.users_page'))

    # Prevent deactivating the only admin
    if user.role == 'admin' and not user.is_active:
        active_admins = User.query.filter_by(role='admin', is_active=True).count()
        if active_admins <= 1:
            flash('Cannot deactivate the only active admin', 'error')
            return redirect(url_for('auth.users_page'))

    user.is_active = not user.is_active
    db.session.commit()

    action = 'activated' if user.is_active else 'deactivated'
    log_activity('user_toggled', f'Admin {action} user: {user.username}', endpoint='auth.toggle_active', method='POST')
    flash(f'User {user.username} {action}', 'success')
    return redirect(url_for('auth.users_page'))

@auth_bp.route('/admin/users/<int:user_id>/assign-role', methods=['POST'])
@admin_required
def assign_role(user_id):
    """Assign role to user"""
    user = User.query.get(user_id)
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('auth.users_page'))

    new_role = request.form.get('role', 'user')
    if new_role not in ['admin', 'user']:
        flash('Invalid role', 'error')
        return redirect(url_for('auth.users_page'))

    old_role = user.role
    user.role = new_role
    db.session.commit()

    log_activity('user_role_changed', f'Admin changed {user.username} role from {old_role} to {new_role}', endpoint='auth.assign_role', method='POST')
    flash(f'Role for {user.username} changed to {new_role}', 'success')
    return redirect(url_for('auth.users_page'))

@auth_bp.route('/admin/activity-logs', methods=['GET'])
@admin_required
def activity_logs_page():
    """Display activity logs"""
    page = request.args.get('page', 1, type=int)
    user_filter = request.args.get('user', '')
    action_filter = request.args.get('action', '')

    query = UserActivityLog.query

    if user_filter:
        query = query.filter_by(username=user_filter)

    if action_filter:
        query = query.filter_by(action_type=action_filter)

    logs = query.order_by(UserActivityLog.timestamp.desc()).paginate(page=page, per_page=50)

    users = User.query.order_by(User.username).all()
    actions = db.session.query(UserActivityLog.action_type).distinct().order_by(UserActivityLog.action_type).all()
    action_types = [a[0] for a in actions]

    return render_template('admin/activity_logs.html', logs=logs, users=users, action_types=action_types, user_filter=user_filter, action_filter=action_filter)
