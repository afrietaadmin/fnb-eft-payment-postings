import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # FNB API
    FNB_BASE_URL = os.getenv('BASE_URL')
    FNB_AUTH_URL = os.getenv('AUTH_URL')
    FNB_TRANSACTION_HISTORY_URL = os.getenv('TRANSACTION_HISTORY_URL')
    FNB_CLIENT_ID = os.getenv('CLIENT_ID')
    FNB_CLIENT_SECRET = os.getenv('CLIENT_SECRET')
    FNB_ACCOUNT_NUMBER1 = os.getenv('ACCOUNT_NUMBER1')
    FNB_ACCOUNT_NUMBER2 = os.getenv('ACCOUNT_NUMBER2')

    # UISP
    UISP_BASE_URL = os.getenv('UISP_BASE_URL')
    UISP_API_KEY = os.getenv('UISP_API_KEY')
    UISP_AUTHORIZATION = os.getenv('UISP_AUTHORIZATION', 'X-Auth-App-Key')

    ***REMOVED***
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # Database
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:////srv/applications/fnb_EFT_payment_postings/data/fnb_transactions.db')
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Application
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', '/var/log/fnb_postings.log')
    TELEGRAM_MESSAGES_FILE = os.getenv('TELEGRAM_MESSAGES_FILE', '/srv/applications/fnb_EFT_payment_postings/telegram_messages.json')
    BASE_PATH = '/srv/applications/fnb_EFT_payment_postings'
    SECRET_KEY = os.getenv('SECRET_KEY', 'default-insecure-key')
    USERS = os.getenv('USERS', '')
    TEST_MODE = os.getenv('TEST_MODE', 'true').lower() == 'true'

    # Filtering
    EXCLUDED_TERMS = {'FNB APP TRANSFER FROM SUBSCRIPTIONS', 'SUBSCRIPTIONS', 'SUBSCRIPTION', 'SHAHIN'}
    FETCH_DAYS_BACK = int(os.getenv('FETCH_DAYS_BACK', '5'))
    POST_CUTOFF_DAYS = int(os.getenv('POST_CUTOFF_DAYS', '6'))
    DUPLICATE_DETECTION_DAYS = int(os.getenv('DUPLICATE_DETECTION_DAYS', '6'))
    DUPLICATE_WINDOW_DAYS = int(os.getenv('DUPLICATE_WINDOW_DAYS', '6'))
