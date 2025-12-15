# Suspension Feature - Implementation Guide

## Quick Start

### Step 1: Create Database Tables

```bash
cd /srv/applications/fnb_EFT_payment_postings
python scripts/migrate_suspension_tables.py
```

**Expected Output:**
```
✅ Successfully created/verified all tables:
   - Customer
   - Service
   - Invoice
   - CachedPayment
   - Suspension
   - PaymentPattern
```

### Step 2: Verify UISP Configuration

Ensure your `.env` file has these entries:

```env
UISP_BASE_URL=https://uisp-ros1.afrieta.com/crm/api/
UISP_API_KEY=your-api-key-here
UISP_AUTHORIZATION=X-Auth-App-Key
```

### Step 3: Restart the Application

The suspension blueprint is automatically registered in `app/__init__.py`, so just restart Flask:

```bash
# If running with Gunicorn/WSGI
sudo systemctl restart fnb-payment-app

# Or if running with Flask dev server
python run.py
```

### Step 4: Access the Feature

Navigate to: `http://your-domain/suspensions`

You should see:
- Navigation link for "Suspensions" in the top menu
- List of current suspensions
- "View Candidates" button for customers needing suspension

## What Was Implemented

### 1. Database Schema

**New Tables Created:**

| Table | Purpose |
|-------|---------|
| `customers` | Cache of customer data from UISP |
| `services` | Customer services/subscriptions |
| `invoices` | Invoice records for analysis |
| `cached_payments` | Payment history cache |
| `suspensions` | Suspension records & audit trail |
| `payment_patterns` | Payment behavior analysis |

**Key Fields:**

- `Customer.grace_payment_date` - Day of month when payment is due (1-31)
- `Customer.is_vip` - VIP status (prevents suspension)
- `Service.status` - active, suspended, prepared, quoted
- `Suspension.is_active` - True = currently suspended, False = resolved
- `PaymentPattern.is_risky` - True if payment behavior is concerning

### 2. UISP Integration Handler

**File:** `app/uisp_suspension_handler.py`

**Features:**
- Fetches customer data from UISP (with 24-hour caching)
- Retrieves customer services
- Caches invoices (last 6 months)
- Caches payments (last 6 months)
- Analyzes payment patterns
- Determines suspension eligibility
- Calls UISP API to suspend/reactivate services

**Key Methods:**
```python
handler.fetch_and_cache_client(client_id)
handler.fetch_and_cache_services(customer)
handler.fetch_and_cache_invoices(customer)
handler.fetch_and_cache_payments(customer)
handler.analyze_payment_pattern(customer)
handler.should_suspend_service(customer, grace_override=False)
handler.suspend_service_uisp(service_id)
handler.reactivate_service_uisp(service_id)
```

### 3. Web UI Routes

**File:** `app/suspension_routes.py`

**Pages:**

1. **List Suspensions** (`/suspensions/`)
   - View all suspensions with filtering
   - Active, resolved, or all
   - Reactivate services directly

2. **Suspension Candidates** (`/suspensions/candidates`)
   - Identifies customers who should be suspended
   - Shows suspension reason
   - Payment pattern analysis
   - Bulk suspension support

3. **Customer Details** (`/suspensions/customer/<id>`)
   - Complete customer view
   - Service list
   - Invoice history
   - Payment patterns
   - Suspension history
   - Individual suspend/reactivate

### 4. Templates

**Files Created:**

1. `app/templates/suspensions/list.html`
   - Lists all suspensions with filters
   - Shows suspension reason and dates
   - Reactivate button for active suspensions

2. `app/templates/suspensions/candidates.html`
   - Lists customers meeting suspension criteria
   - Bulk selection and suspension
   - Payment pattern display
   - Risk indicators

3. `app/templates/suspensions/customer_details.html`
   - Comprehensive customer view
   - Invoice table with status
   - Service list with actions
   - Payment pattern metrics
   - Suspension history
   - Manual refresh from UISP

### 5. Suspension Logic

**Rules Implemented:**

✅ **Suspension Allowed If:**
- Customer has overdue invoices
- 2+ missed payments in last 6 months
- 3+ late payments in last 6 months
- Average payment is 30+ days late

❌ **Suspension Blocked If:**
- Customer is marked as VIP
- Current day is before grace payment date
- (`grace_override=true` can force suspension anyway)

### 6. Audit Trail

All suspension actions logged to:
- `user_activity_logs` - Records who did what and when
- `suspensions` table - Detailed suspension history

**Tracked Actions:**
- SUSPEND_SERVICE
- REACTIVATE_SERVICE
- BULK_SUSPEND_SERVICES
- REFRESH_CUSTOMER_CACHE

## API Endpoints Summary

### View Operations

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/suspensions/` | GET | List all suspensions |
| `/suspensions/candidates` | GET | View suspension candidates |
| `/suspensions/customer/<id>` | GET | Customer details |
| `/suspensions/api/dashboard` | GET | Dashboard statistics |

### Action Operations

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/suspensions/api/suspend` | POST | Suspend a service |
| `/suspensions/api/reactivate` | POST | Reactivate a service |
| `/suspensions/api/bulk_suspend` | POST | Suspend multiple services |
| `/suspensions/api/refresh_customer/<id>` | POST | Refresh UISP data |

## Configuration Details

### Grace Period System

**How It Works:**

1. In UISP, set customer attribute: `gracePaymentDate` = day number (1-31)
2. System fetches this value and caches it
3. Customer won't be suspended until after that day
4. Example: `gracePaymentDate = 15` means customer gets until 15th of each month

**In Database:**
```python
customer.grace_payment_date = 15  # Can be suspended after 15th
```

**Checking in Code:**
```python
today = datetime.now().day
if today <= customer.grace_payment_date:
    # Within grace period - won't suspend
```

### VIP Status

**How It Works:**

1. In UISP, set customer attribute: `vip` = "1" for VIP, "0" for not
2. System fetches and caches as `is_vip` boolean
3. VIP customers are NEVER automatically suspended
4. Only manual action can suspend VIP customer

**In Database:**
```python
customer.is_vip = True  # Will NOT be suspended automatically
```

## Typical Workflow

### For Regular Users

1. Login to application
2. Click "Suspensions" in navigation
3. Click "Suspension Candidates" to see who needs suspension
4. Review customer details by clicking their name
5. Click "Suspend Now" or use bulk selection
6. Add note explaining reason
7. Confirm suspension

### For Administrators

1. Monitor "Active Suspensions" page regularly
2. Check dashboard statistics
3. Review payment patterns of risky customers
4. Handle edge cases (VIP customers, special arrangements)
5. Reactivate services when payments received
6. Generate reports from suspension history

### For Finance/Collections

1. Use suspension system as a collections tool
2. Identify customers before they become overdue
3. Monitor payment patterns over time
4. Trigger suspension for chronic non-payers
5. Reactivate quickly when payment received
6. Track success metrics (% reactivated within 7 days)

## Customization Points

### Change Suspension Criteria

Edit `app/uisp_suspension_handler.py`, method `should_suspend_service()`:

```python
def should_suspend_service(self, customer: Customer) -> tuple[bool, str]:
    # Modify conditions here
    # Return (should_suspend: bool, reason: str)
```

### Change Cache Duration

Edit `app/uisp_suspension_handler.py`:

```python
CACHE_DURATION_HOURS = 24  # Change this value
```

### Change Lookback Period

Edit `app/uisp_suspension_handler.py`:

```python
LOOKBACK_DAYS = 180  # Change from 180 (6 months) to desired value
```

### Add Custom Fields

Add to `Customer` model in `app/models.py`:

```python
class Customer(db.Model):
    # ... existing fields ...
    your_custom_field = db.Column(db.String(255), nullable=True)
```

Then run migration again.

## Troubleshooting

### Issue: No suspension candidates found

**Check:**
1. Are customers in database? (`customers` table should have rows)
2. Are there invoices? (`invoices` table)
3. Are there payments? (`cached_payments` table)
4. Do any customers meet criteria? (Run analysis manually)

**Solution:**
```python
# Manually test in Python shell
from app import create_app, db
from app.models import Customer
from app.uisp_suspension_handler import UISPSuspensionHandler

app = create_app()
with app.app_context():
    handler = UISPSuspensionHandler()
    customer = Customer.query.first()
    should_suspend, reason = handler.should_suspend_service(customer)
    print(f"Should suspend: {should_suspend}, Reason: {reason}")
```

### Issue: UISP API errors

**Check .env file:**
```bash
grep UISP /path/to/.env
```

**Verify API key works:**
```bash
curl -H "X-Auth-App-Key: YOUR_KEY" \
  https://uisp-ros1.afrieta.com/crm/api/v2.1/clients/1
```

**Check logs:**
```bash
tail -f /var/log/fnb-payment-app/app.log | grep UISP
```

### Issue: Slow performance

**Causes:**
1. Cache expired - data being fetched fresh
2. Many customers being analyzed
3. Network latency to UISP API

**Solutions:**
1. Refresh customer data during off-peak hours
2. Use bulk operations instead of individual
3. Monitor and optimize network connection

### Issue: Database locked

**In development:**
```bash
rm /path/to/database.db-journal
```

**In production:**
- Check for long-running queries
- Verify no concurrent updates
- Consider read replicas

## Performance Tips

1. **Cache Effectively**
   - Let 24-hour cache work
   - Only refresh when needed
   - Don't force refresh for all customers daily

2. **Bulk Operations**
   - Use bulk suspend for multiple customers
   - Much faster than individual calls
   - Reduces API rate limit pressure

3. **Indexing**
   - System has proper indexes on common queries
   - Monitor slow query log
   - Add indexes if new queries are added

4. **Database Maintenance**
   - Archive old suspensions (>1 year)
   - Vacuum/optimize database periodically
   - Monitor table sizes

## Next Steps

1. **Test the feature** in a non-production environment first
2. **Verify UISP integration** with test customer
3. **Train staff** on suspension workflow
4. **Monitor** suspension/reactivation metrics
5. **Iterate** based on business needs

## Support

For questions or issues:
1. Check `SUSPENSION_FEATURE.md` for detailed documentation
2. Review logs: Check Flask app logs for errors
3. Test UISP connectivity directly
4. Verify database tables were created
5. Check that migrations ran successfully

## Files Created/Modified

### New Files

- `app/uisp_suspension_handler.py` - UISP integration
- `app/suspension_routes.py` - Web routes
- `app/templates/suspensions/list.html` - Suspension list
- `app/templates/suspensions/candidates.html` - Candidates list
- `app/templates/suspensions/customer_details.html` - Customer details
- `scripts/migrate_suspension_tables.py` - Database migration
- `SUSPENSION_FEATURE.md` - Detailed documentation
- `SUSPENSION_IMPLEMENTATION_GUIDE.md` - This file

### Modified Files

- `app/models.py` - Added 6 new models
- `app/__init__.py` - Registered suspension blueprint
- `app/templates/base.html` - Added navigation link

## Statistics

- **Lines of Code**: ~2,500
- **Database Tables**: 6 new
- **API Endpoints**: 8 new
- **Templates**: 3 new
- **Models**: 6 new
- **Features**: 15+ major features

---

**Implementation Complete** ✅

The suspension feature is ready for use. Follow the Quick Start section above to get started.
