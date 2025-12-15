# Service Suspension Feature Documentation

## Overview

The Service Suspension feature enables automated detection and management of customers who should have their services suspended due to non-payment or consistent payment issues. The system integrates with UISP to suspend/reactivate services while maintaining a local audit trail of all suspension actions.

## Architecture

### Key Components

1. **UISPSuspensionHandler** (`app/uisp_suspension_handler.py`)
   - Manages all UISP API interactions
   - Implements local caching of customer data
   - Analyzes payment patterns
   - Determines suspension eligibility
   - Executes suspend/reactivate operations

2. **Database Models** (`app/models.py`)
   - `Customer`: Customer information cache from UISP
   - `Service`: Service/subscription records
   - `Invoice`: Invoice data for analysis
   - `CachedPayment`: Payment history cache
   - `Suspension`: Suspension history and audit trail
   - `PaymentPattern`: Payment behavior analysis

3. **Suspension Routes** (`app/suspension_routes.py`)
   - `/suspensions/` - List all suspensions
   - `/suspensions/candidates` - View customers who should be suspended
   - `/suspensions/customer/<id>` - View customer details and suspension history
   - API endpoints for suspend/reactivate operations
   - Bulk operation endpoints

4. **Web UI Templates** (`app/templates/suspensions/`)
   - `list.html` - Suspension list and management
   - `candidates.html` - Suspension candidates with bulk actions
   - `customer_details.html` - Detailed customer view with history

## Suspension Logic

### Criteria for Suspension

A customer is eligible for suspension if ANY of the following conditions are met:

1. **Overdue Invoices**: One or more invoices are past due
2. **Missed Payments**: 2 or more missed payments in the last 6 months
3. **Late Payment Pattern**: 3 or more late payments in the last 6 months
4. **High Risk Pattern**: Average days late exceeds 30 days

### Conditions that PREVENT Suspension

1. **VIP Status**: Customer tagged as VIP in UISP (never automatically suspend)
2. **Grace Period**: Current day is before the customer's grace payment date
3. **Manual Override**: Administrator can force suspension via `grace_override` flag

### How Grace Period Works

- Stored in UISP as `gracePaymentDate` attribute (integer 1-31)
- Example: If `gracePaymentDate = 15`, customer won't be suspended until after the 15th of each month
- Can be overridden during suspension action with `grace_override=true`

## Installation & Setup

### 1. Run Database Migration

```bash
cd /srv/applications/fnb_EFT_payment_postings
python scripts/migrate_suspension_tables.py
```

This creates the following tables:
- `customers`
- `services`
- `invoices`
- `cached_payments`
- `suspensions`
- `payment_patterns`

### 2. Verify UISP API Configuration

Ensure your `.env` file includes:
```env
UISP_BASE_URL=https://uisp-ros1.afrieta.com/crm/api/
UISP_API_KEY=your-api-key
UISP_AUTHORIZATION=X-Auth-App-Key
```

## Usage

### Web UI Access

1. **Navigate to Suspensions**: Click "Suspensions" in the main navigation menu
2. **View Active Suspensions**: See all currently active suspensions
3. **View Candidates**: Check customers who should be suspended
4. **Suspend Services**: Individual or bulk suspension with audit trail

### Suspension Candidates View

This view automatically identifies customers who meet suspension criteria:

1. Fetches all active customers from database
2. Evaluates suspension logic for each
3. Displays reasons for suspension
4. Shows payment pattern analysis
5. Allows individual or bulk suspension

**Features:**
- Color-coded risk indicators
- Payment pattern metrics
- Grace period information
- VIP status display
- One-click or bulk suspend

### Customer Details View

Complete view of a single customer:

1. **Customer Information**: Contact, balance, VIP status
2. **Suspension History**: All past and current suspensions
3. **Services**: List of active/suspended services
4. **Payment Pattern Analysis**: Detailed payment behavior
5. **Recent Invoices**: Last 10 invoices with status

**Features:**
- Refresh data from UISP on-demand
- Suspend/reactivate services
- Add notes to suspensions
- View invoice details

### Bulk Operations

The system supports bulk suspension:

1. Select multiple candidates using checkboxes
2. Click "Suspend Selected"
3. All services suspended in parallel
4. Results report shows success/failures

## API Endpoints

### GET /suspensions/
List all suspensions with filters:
- `filter=all` - All suspensions
- `filter=active` - Active only
- `filter=resolved` - Resolved only

### GET /suspensions/candidates
List customers eligible for suspension with pagination.

### GET /suspensions/customer/<customer_id>
Get detailed view of customer with suspension history.

### POST /suspensions/api/suspend
Suspend a service.

**Request:**
```json
{
  "customer_id": 1,
  "service_id": 5,
  "reason": "Non-payment",
  "note": "Optional note",
  "grace_override": false
}
```

### POST /suspensions/api/reactivate
Reactivate a suspended service.

**Request:**
```json
{
  "suspension_id": 10,
  "note": "Optional reactivation note"
}
```

### POST /suspensions/api/bulk_suspend
Suspend multiple services at once.

**Request:**
```json
{
  "suspensions": [
    {
      "customer_id": 1,
      "service_id": 5,
      "reason": "Non-payment"
    },
    {
      "customer_id": 2,
      "service_id": 10,
      "reason": "Non-payment"
    }
  ]
}
```

### POST /suspensions/api/refresh_customer/<customer_id>
Refresh cached data from UISP for a customer.

### GET /suspensions/api/dashboard
Get suspension dashboard statistics.

**Response:**
```json
{
  "active_suspensions": 5,
  "resolved_suspensions": 12,
  "vip_customers": 8,
  "customers_with_overdue": 15,
  "risky_patterns": 22,
  "active_services": 150,
  "suspended_services": 5,
  "recent_suspensions": 3
}
```

## Data Caching Strategy

### Why Caching?

UISP API has rate limits. Caching reduces API calls while maintaining accuracy:

- **Customer Data**: 24-hour cache (refreshed on-demand)
- **Services**: 24-hour cache
- **Invoices**: 24-hour cache (last 6 months)
- **Payments**: 24-hour cache (last 6 months)

### Cache Invalidation

Cache is automatically refreshed:
1. Every 24 hours (on next access)
2. When manually triggered via API
3. Always fetched fresh on first access

### Manual Refresh

Click "Refresh from UISP" on customer details page to force a fresh fetch.

## Audit Trail

Every suspension/reactivation action is logged:

1. **User Activity Logs** table records:
   - Action type (SUSPEND_SERVICE, REACTIVATE_SERVICE, BULK_SUSPEND)
   - User who performed action
   - Timestamp
   - IP address
   - User agent

2. **Suspensions** table records:
   - Customer and service IDs
   - Suspension reason
   - Suspension date and user
   - Reactivation date and user
   - Notes

## Payment Pattern Analysis

The system analyzes payment history to identify risky customers:

### Metrics Calculated

- **On-Time Payments**: Count of payments made by due date
- **Late Payments**: Count of payments made after due date
- **Missed Payments**: Count of unpaid/overdue invoices
- **Average Days Late**: Mean days payment was overdue
- **Average Payment Amount**: Mean payment amount
- **Risk Flag**: Set if risky pattern detected

### Risk Determination

A customer is flagged as "risky" if:
- 2+ missed payments, OR
- 3+ late payments, OR
- Average days late exceeds 30 days

## Integration with Existing System

### Transaction Processing

The suspension feature works alongside existing payment posting:

1. Payment comes in via FNB EFT
2. Posted to UISP via existing system
3. Automatically applied to invoices
4. Suspension system monitors ongoing payment patterns
5. Takes action when criteria met

### Audit Integration

Uses existing `user_activity_logs` table for:
- Recording all suspensions/reactivations
- User attribution
- Compliance and reporting

## Troubleshooting

### Common Issues

**1. Tables not created**
```bash
python scripts/migrate_suspension_tables.py
```

**2. UISP API errors**
- Check API key in `.env`
- Verify base URL format
- Check network connectivity
- Review API response in logs

**3. Empty suspension candidates list**
- Ensure customers are synced via `/suspensions/api/refresh_customer`
- Check payment pattern analysis results
- Verify suspension criteria in `should_suspend_service()`

**4. Slow performance**
- Cache may be 24 hours old
- Click "Refresh from UISP" to force fresh data
- Check network/API performance

## Performance Considerations

### Database Indexes

Suspension feature uses indexes for fast queries:

```python
# Customer lookups
idx_uisp_client_id (unique, indexed)

# Service lookups
idx_uisp_service_id (unique, indexed)

# Suspension queries
idx_customer_active (customer_id, is_active)
idx_service_active (uisp_service_id, is_active)

# Payment analysis
idx_customer_created (customer_id, created_date)
```

### Optimization Tips

1. Refresh customer data during off-peak hours
2. Use bulk suspend when possible
3. Archive old suspensions periodically
4. Monitor database size with 6-month lookback

## Configuration Options

### Environment Variables

```env
# UISP API
UISP_BASE_URL=https://uisp-ros1.afrieta.com/crm/api/
UISP_API_KEY=your-key
UISP_AUTHORIZATION=X-Auth-App-Key

# Flask
SECRET_KEY=your-secret
DATABASE_URL=sqlite:////path/to/db
TEST_MODE=false
```

### Code Configuration

In `app/uisp_suspension_handler.py`:

```python
CACHE_DURATION_HOURS = 24      # Cache expiration
LOOKBACK_DAYS = 180            # 6 months history analysis
```

## Future Enhancements

Potential improvements for future releases:

1. **Automated Scheduling**: Run suspension checks on a cron schedule
2. **Email Notifications**: Alert customers before suspension
3. **Partial Suspension**: Suspend specific services, keep others active
4. **Payment Arrangement**: Track and honor payment arrangements
5. **SMS Alerts**: Notify customers of overdue status
6. **Dashboard Widgets**: Suspension metrics on main dashboard
7. **Export Reports**: CSV/PDF reports of suspensions
8. **Webhook Notifications**: Send suspension events to external systems

## Support & Maintenance

### Regular Maintenance

1. **Weekly**: Monitor active suspensions, review reactivations
2. **Monthly**: Analyze payment patterns, identify trends
3. **Quarterly**: Review suspension policy effectiveness
4. **Annually**: Archive old suspension records

### Monitoring

Key metrics to track:

- Active suspensions count
- Reactivation rate (% reactivated within 7 days)
- Payment collection after reactivation
- Average time to reactivation
- VIP customer suspension incidents (should be zero)

## License

This feature is part of the FNB EFT Payment Postings system.
