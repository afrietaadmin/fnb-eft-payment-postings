# FNB EFT Payment Postings - Setup Guide

## Project Structure
```
/srv/applications/fnb_EFT_payment_postings/
├── app/
│   ├── __init__.py              # Flask app factory
│   ├── config.py                # Centralized config from .env
│   ├── models.py                # SQLAlchemy models
│   ├── routes.py                # Web UI routes
│   ├── utils.py                 # Helper functions
│   └── templates/               # HTML templates
├── scripts/
│   ├── fetch_fnb_transactions.py  # Fetch from FNB API
│   ├── sanitize_data.py           # Extract CID from transactions
│   └── post_payments_UISP.py      # Post to UISP
├── data/                        # SQLite database location
├── logs/                        # Log files
├── venv/                        # Python virtual environment
├── wsgi.py                      # Flask WSGI entry point
├── run_schedule.py              # Scheduler daemon
├── telegram_notifier.py         ***REMOVED*** alerting
├── requirements.txt             # Python dependencies
├── .env                         # Configuration (COPY FROM .env.template)
└── .env.template                # Configuration template
```

## Setup Steps

### 1. Copy .env template
```bash
cp /srv/applications/fnb_EFT_payment_postings/.env.template /srv/applications/fnb_EFT_payment_postings/.env
```

### 2. Edit .env with your credentials
```bash
nano /srv/applications/fnb_EFT_payment_postings/.env
```

Fill in:
- FNB API credentials (BASE_URL, AUTH_URL, CLIENT_ID, CLIENT_SECRET, ACCOUNT_NUMBERs)
- UISP API credentials (UISP_BASE_URL, UISP_API_KEY)
- Telegram credentials (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

### 3. Initialize database
```bash
cd /srv/projects/fnb_EFT_payment_postings
./venv/bin/python -c "
from app import create_app
app = create_app()
with app.app_context():
    print('Database initialized successfully')
"
```

## Running the Application

### Run Scheduler (Main Process)
```bash
/srv/applications/fnb_EFT_payment_postings/venv/bin/python /srv/applications/fnb_EFT_payment_postings/run_schedule.py
```

### Run Individual Scripts Manually
```bash
# Fetch transactions
/srv/applications/fnb_EFT_payment_postings/venv/bin/python /srv/applications/fnb_EFT_payment_postings/scripts/fetch_fnb_transactions.py

# Sanitize CIDs
/srv/applications/fnb_EFT_payment_postings/venv/bin/python /srv/applications/fnb_EFT_payment_postings/scripts/sanitize_data.py

# Post to UISP
/srv/applications/fnb_EFT_payment_postings/venv/bin/python /srv/applications/fnb_EFT_payment_postings/scripts/post_payments_UISP.py

# Send Telegram notification
/srv/applications/fnb_EFT_payment_postings/venv/bin/python /srv/applications/fnb_EFT_payment_postings/telegram_notifier.py
```

### Run Web UI
```bash
cd /srv/projects/fnb_EFT_payment_postings
./venv/bin/python wsgi.py
# Access at http://localhost:5000
```

## Database Schema

### Transactions Table
- `id` - Primary key
- `entryId` - FNB API transaction ID (unique)
- `account` - Bank account number
- `amount` - Transaction amount
- `valueDate` - Date of transaction
- `remittance_info` - Payment description
- `reference` - Payment reference
- `CID` - Customer ID (unallocated if not found)
- `posted` - yes/no
- `UISPpaymentId` - UISP payment ID if posted
- `postedDate` - When posted to UISP
- `status` - pending/ready_to_post/posted/failed
- `timestamp` - When transaction was fetched

### FailedTransaction Table
- `id` - Primary key
- `entryId` - Foreign key to Transaction
- `reason` - Why it failed
- `error_code` - HTTP status or error code
- `manual_cid` - CID provided manually via web UI
- `resolved` - Boolean
- `resolved_at` - When manually resolved

### AuditLog Table
- Tracks all changes to transactions
- Records: action, field, old_value, new_value, changed_by, timestamp

### ExecutionLog Table
- Logs each script execution
- Records: script_name, status, transactions_processed, failed, total_amount

## Key Changes from Original

✅ **Removed Firestore** - Uses SQLite instead (local DB)
✅ **Uses entryId** - No hash generation, uses FNB API transaction ID directly
✅ **Centralized Config** - All credentials in .env file
✅ **Web UI** - http://localhost:5000 to manage failed transactions
✅ **Audit Trail** - Complete history of transaction changes
✅ **Better Logging** - Structured logging to DB + files
✅ **Manual Remediation** - UI to assign correct CID and re-post
✅ **Execution Tracking** - View script runs and results

## Monitoring

- Dashboard: http://localhost:5000
- Failed transactions: http://localhost:5000/failed
- All transactions: http://localhost:5000/transactions
- Execution logs: http://localhost:5000/execution-logs
- Telegram: Automatic alerts

## Troubleshooting

Check logs:
```bash
tail -f /var/log/fnb_postings.log
```

Check database:
```bash
sqlite3 /srv/applications/fnb_EFT_payment_postings/data/fnb_transactions.db
```

View failed transactions:
```sql
SELECT entryId, reason, resolved FROM failed_transactions WHERE resolved = 0;
```
