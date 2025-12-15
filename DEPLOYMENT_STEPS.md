# Suspension Feature Deployment Steps

## Prerequisites

- FNB EFT Payment Postings application installed and running
- UISP API credentials (already configured)
- Database write access
- Admin/deployment permissions

## Step-by-Step Deployment

### Step 1: Verify Files Are in Place

All files have been created. Verify they exist:

```bash
cd /srv/applications/fnb_EFT_payment_postings

# Check core files
test -f app/uisp_suspension_handler.py && echo "✅ Handler exists"
test -f app/suspension_routes.py && echo "✅ Routes exist"
test -f scripts/migrate_suspension_tables.py && echo "✅ Migration script exists"

# Check templates
test -d app/templates/suspensions && echo "✅ Templates exist"
ls app/templates/suspensions/

# Check documentation
test -f SUSPENSION_FEATURE.md && echo "✅ Feature docs exist"
test -f SUSPENSION_IMPLEMENTATION_GUIDE.md && echo "✅ Implementation guide exists"
test -f SUSPENSION_SUMMARY.txt && echo "✅ Summary exists"
```

### Step 2: Backup Current Database

Before running migrations, create a backup:

```bash
# If using SQLite (default)
cp /srv/projects/fnb_EFT_payment_postings/data/fnb_transactions.db \
   /srv/projects/fnb_EFT_payment_postings/data/fnb_transactions.db.backup.$(date +%Y%m%d)

echo "✅ Database backed up"

# Or if using PostgreSQL/MySQL, use your backup tool
```

### Step 3: Create Database Tables

Run the migration script:

```bash
cd /srv/applications/fnb_EFT_payment_postings

# Activate virtual environment if needed
source venv/bin/activate

# Run migration
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

Migration complete!
```

**If migration fails:**
- Check database connectivity
- Verify database file/server is accessible
- Check logs for specific errors
- Restore from backup if needed

### Step 4: Verify Application Changes

The following changes have been made automatically:

1. **Models** (`app/models.py`):
   - Added 6 new model classes
   - Already imported and registered

2. **Blueprint** (`app/__init__.py`):
   - Suspension blueprint registered
   - Already added to app initialization

3. **Navigation** (`app/templates/base.html`):
   - Suspensions link added to navbar
   - Already integrated

No manual code changes needed - everything is ready!

### Step 5: Restart Application

Restart the Flask/WSGI application:

```bash
# If using systemd
sudo systemctl restart fnb-payment-app

# If using Gunicorn
sudo systemctl restart gunicorn

# If running Flask directly (development only)
# Stop current process (Ctrl+C) and restart
python run.py
```

### Step 6: Verify Deployment

Check that the application is running and suspension feature is accessible:

```bash
# Check application is running
curl -s http://localhost:5000/suspensions | head -20

# Should show HTML with "Suspensions" page or redirect to login
# If you get connection refused, app might not be running
```

### Step 7: Verify in Web UI

1. Open application: `http://your-domain:5000`
2. Log in with admin credentials
3. Look for "Suspensions" link in navigation menu
4. Click on it - you should see an empty suspensions list (nothing suspended yet)
5. Click "Suspension Candidates" - initially empty until data is synced

### Step 8: Sync Customer Data from UISP

The suspension feature uses cached data. To populate it:

**Option A: Manual Sync (Recommended for first deployment)**

1. Go to a customer details page
2. Find the "Refresh from UISP" button
3. Click it to fetch that customer's data
4. Repeat for key customers

**Option B: Programmatic Sync**

```python
from app import create_app, db
from app.models import Customer
from app.uisp_suspension_handler import UISPSuspensionHandler

app = create_app()
with app.app_context():
    handler = UISPSuspensionHandler()
    
    # Sync first 10 customers
    customers = Customer.query.all()[:10]
    for customer in customers:
        print(f"Syncing customer {customer.uisp_client_id}...")
        handler.fetch_and_cache_client(customer.uisp_client_id)
        handler.fetch_and_cache_services(customer)
        handler.fetch_and_cache_invoices(customer)
        handler.fetch_and_cache_payments(customer)
        handler.analyze_payment_pattern(customer)
    
    print("✅ Sync complete")
```

### Step 9: Test Suspension Feature

1. Go to "Suspensions" → "Suspension Candidates"
2. If customers are synced, you should see candidates listed
3. Review one customer by clicking their name
4. Verify their details, services, and invoices load
5. Try suspending one service (this will actually call UISP)
6. Check suspension appears in UISP (optional but recommended)
7. Reactivate the service
8. Verify it's marked as resolved

### Step 10: Monitor Initial Deployment

In the first 24-48 hours:

1. Check application logs for errors
2. Monitor UISP API usage (ensure it's not exceeded)
3. Review suspended services list
4. Verify reactivations work
5. Check audit logs show correct user attribution
6. Confirm no suspension errors in logs

## Troubleshooting Deployment

### Issue: Migration Script Fails

**Check database:**
```bash
# SQLite
sqlite3 /srv/projects/fnb_EFT_payment_postings/data/fnb_transactions.db ".tables"

# Should show existing tables like transactions, failed_transactions, etc.
```

**Check permissions:**
```bash
# Database file should be writable
ls -la /srv/projects/fnb_EFT_payment_postings/data/fnb_transactions.db
```

**Restore and retry:**
```bash
cp /srv/projects/fnb_EFT_payment_postings/data/fnb_transactions.db.backup.* \
   /srv/projects/fnb_EFT_payment_postings/data/fnb_transactions.db
python scripts/migrate_suspension_tables.py
```

### Issue: Suspensions Link Not Appearing

**Check app restarted:**
```bash
systemctl status fnb-payment-app
```

**Check blueprint registered:**
```bash
ps aux | grep python | grep fnb
# Make sure process is running the latest version
```

**Force app reload:**
```bash
# Kill and restart
sudo systemctl stop fnb-payment-app
sudo systemctl start fnb-payment-app
```

### Issue: UISP API Errors

**Check credentials:**
```bash
grep UISP /path/to/.env
```

**Test API directly:**
```bash
curl -H "X-Auth-App-Key: YOUR_API_KEY" \
  https://uisp-ros1.afrieta.com/crm/api/v2.1/clients/1
```

**Check logs:**
```bash
tail -f /var/log/fnb-payment-app/app.log | grep -i uisp
```

### Issue: Database Locked Error

**SQLite specific:**
```bash
# Remove lock files
rm /path/to/database.db-journal
rm /path/to/database.db-wal
```

**Restart application:**
```bash
sudo systemctl restart fnb-payment-app
```

### Issue: Suspensions Page Empty

**Is data cached?**
- Cache only populates when you view customer details
- Click "Refresh from UISP" on a customer to populate data
- Wait for page to load (data is being fetched)

**Check database populated:**
```bash
sqlite3 /srv/projects/fnb_EFT_payment_postings/data/fnb_transactions.db
sqlite> SELECT COUNT(*) FROM customers;
sqlite> SELECT COUNT(*) FROM services;
```

If counts are 0, no data has been synced yet.

## Post-Deployment Checklist

- [ ] Database migration completed successfully
- [ ] Application restarted
- [ ] "Suspensions" link visible in navigation
- [ ] Can access /suspensions/ page
- [ ] "Suspension Candidates" page accessible
- [ ] At least one customer data synced from UISP
- [ ] No errors in application logs
- [ ] UISP API connectivity verified
- [ ] Test suspension created and verified in UISP
- [ ] Test reactivation works
- [ ] Audit logs show correct entries

## Rollback Procedure

If deployment encounters critical issues:

### Option 1: Database Only
```bash
# Restore database backup
cp /srv/projects/fnb_EFT_payment_postings/data/fnb_transactions.db.backup.YYYYMMDD \
   /srv/projects/fnb_EFT_payment_postings/data/fnb_transactions.db

# Restart app
sudo systemctl restart fnb-payment-app
```

The old tables won't exist, but the feature will deactivate gracefully.

### Option 2: Complete Rollback
If you want to completely remove the feature:

1. Restore database backup
2. Revert git changes (if using git):
```bash
git checkout HEAD -- app/models.py app/__init__.py app/templates/base.html
```
3. Remove feature files:
```bash
rm -f app/uisp_suspension_handler.py
rm -f app/suspension_routes.py
rm -rf app/templates/suspensions/
```
4. Restart application

## Next Steps After Deployment

1. **Initial Setup** (Day 1):
   - Sync 5-10 key customers from UISP
   - Test suspension flow with non-critical customer
   - Review audit logs
   - Train staff on feature usage

2. **First Week**:
   - Monitor API usage and performance
   - Review suspension candidates daily
   - Verify UISP synchronization working
   - Adjust suspension criteria if needed

3. **First Month**:
   - Review all suspensions made
   - Analyze reactivation patterns
   - Monitor customer complaints/inquiries
   - Generate usage report

4. **Ongoing**:
   - Daily review of suspension candidates
   - Weekly reactivation checks
   - Monthly reporting to management
   - Quarterly policy review

## Support

For issues or questions during deployment:

1. Check DEPLOYMENT_STEPS.md (this file)
2. Review SUSPENSION_IMPLEMENTATION_GUIDE.md
3. Check SUSPENSION_FEATURE.md for detailed reference
4. Review application logs for specific errors
5. Test UISP API connectivity directly

## Success Indicators

✅ Feature is successfully deployed when:

- [ ] Suspensions link appears in navigation
- [ ] Can view suspension candidates
- [ ] Can view customer details page
- [ ] Can suspend a service
- [ ] Service status updates in UISP
- [ ] Can reactivate a service
- [ ] Suspension appears in audit logs
- [ ] No critical errors in logs

---

**Deployment Status**: Ready

The suspension feature is ready for production deployment. Follow these steps to activate it.
