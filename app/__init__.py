from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
import os

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)

def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:////srv/applications/fnb_EFT_payment_postings/data/fnb_transactions.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    secret_key = os.getenv('SECRET_KEY')
    if not secret_key or secret_key == 'default-insecure-key':
        raise RuntimeError('SECRET_KEY environment variable must be set to a strong random value. '
                           'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"')
    app.config['SECRET_KEY'] = secret_key

    # Trust X-Forwarded headers from reverse proxy
    app.config['PREFERRED_URL_SCHEME'] = 'https'
    app.config['REAL_IP_ONLY'] = False

    # Apply ProxyFix middleware to handle reverse proxy headers
    # x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=0
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Flask-Login configuration
    app.config['REMEMBER_COOKIE_DURATION'] = 86400 * 30  # 30 days
    app.config['REMEMBER_COOKIE_SECURE'] = True
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'

    # Session configuration
    app.config['SESSION_COOKIE_SECURE'] = False  # Allow HTTP for internal use
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = 28800  # 8 hours

    # CSRF Protection
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['WTF_CSRF_TIME_LIMIT'] = None  # CSRF tokens never expire

    # Rate limiting
    app.config['RATELIMIT_STORAGE_URL'] = 'memory://'

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.login_view = 'auth.login'

    with app.app_context():
        from . import models
        db.create_all()

        from .routes import main_bp
        app.register_blueprint(main_bp)

        from .auth_routes import auth_bp
        app.register_blueprint(auth_bp)

        from .suspension_routes import suspension_bp
        app.register_blueprint(suspension_bp)

    @login_manager.user_loader
    def load_user(user_id):
        from .models import User
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_stats():
        """Make stats available to all templates."""
        from .models import Transaction, FailedTransaction
        try:
            stats = {
                'total_transactions': Transaction.query.count(),
                'posted': Transaction.query.filter_by(posted='yes').count(),
                'pending': Transaction.query.filter_by(posted='no').count(),
                'failed': FailedTransaction.query.filter_by(resolved=False).count(),
            }
        except Exception:
            # If database is not available, return empty stats
            stats = {
                'total_transactions': 0,
                'posted': 0,
                'pending': 0,
                'failed': 0,
            }
        return dict(stats=stats)

    return app
