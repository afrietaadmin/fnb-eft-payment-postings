# Suspension Feature - Logic & API Calls Documentation

**Date:** 2025-12-14
**Status:** Comprehensive Reference
**File:** SUSPENSIONS_LOGIC_AND_API.md

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Data Flow](#data-flow)
3. [Suspension Logic](#suspension-logic)
4. [API Endpoints](#api-endpoints)
5. [UISP Integration](#uisp-integration)
6. [Web UI Interactions](#web-ui-interactions)
7. [Database Schema](#database-schema)
8. [Code Location Reference](#code-location-reference)

---

## Overview

The suspension feature is a complete system for managing customer service suspensions based on payment behavior. It operates in three main layers:

1. **Data Layer** - SQLite database with 6 suspension-related tables
2. **Business Logic Layer** - UISP handler with caching & analysis
3. **API/Web Layer** - REST endpoints and web UI for management

### Key Characteristics

- **Smart Caching** - 24-hour cache to reduce UISP API calls
- **Payment Pattern Analysis** - Identifies late/missed payments
- **VIP Protection** - VIP customers never automatically suspended
- **Grace Period Support** - Configurable day-of-month grace period
- **Audit Trail** - Every action logged with user & timestamp
- **Real-time Sync** - Can refresh customer data on-demand

---

## Data Flow

### High-Level Flow

```
┌──────────────────┐
│  Web UI / User   │
└────────┬─────────┘
         │
         │ HTTP Request
         ▼
┌──────────────────────────┐
│  Flask Routes            │ (suspension_routes.py)
│  - List suspensions      │
│  - View candidates       │
│  - Suspend/Reactivate    │
└────────┬─────────────────┘
         │
         │ Business Logic
         ▼
┌──────────────────────────┐
│  UISP Handler            │ (uisp_suspension_handler.py)
│  - Fetch customer data   │
│  - Cache in DB           │
│  - Analyze patterns      │
│  - Call UISP APIs        │
└────────┬─────────────────┘
         │
         ├─────────────────────────────────────┐
         │                                     │
         ▼                                     ▼
┌──────────────────┐              ┌──────────────────┐
│  SQLite Database │              │  UISP API        │
│  (Local Cache)   │              │  (External)      │
└──────────────────┘              └──────────────────┘
```

### Data Cache Update Cycle

1. User clicks "Refresh from UISP" on customer details page
2. Flask route `/suspensions/api/refresh_customer/<id>` is called
3. UISP Handler fetches fresh data from UISP API
4. Data is cached locally in database
5. Payment pattern analysis is recalculated
6. Page refreshes to show updated information

---

## Suspension Logic

### Core Decision Tree

The system determines suspension eligibility using this logic:

```
┌─────────────────────────────────┐
│ Should suspend service?         │
└────────────┬────────────────────┘
             │
             ▼
    ┌─────────────────┐
    │ Is customer VIP?│
    └────┬────────────┘
         │ YES
         └──→ ❌ DO NOT SUSPEND
         │ NO
         ▼
    ┌──────────────────────┐
    │ Grace period active? │
    └────┬────────────────┘
         │ YES
         └──→ ❌ DO NOT SUSPEND
         │ NO
         ▼
    ┌──────────────────────────┐
    │ Has overdue invoices?    │
    └────┬────────────────────┘
         │ YES
         └──→ ✅ SUSPEND (reason: X overdue invoices)
         │ NO
         ▼
    ┌──────────────────────────┐
    │ Check payment pattern    │
    └────┬────────────────────┘
         │
         ▼
    ┌──────────────────────┐
    │ 2+ missed payments?  │
    └────┬────────────────┘
         │ YES
         └──→ ✅ SUSPEND (reason: X missed payments)
         │ NO
         ▼
    ┌──────────────────────┐
    │ 3+ late payments?    │
    └────┬────────────────┘
         │ YES
         └──→ ✅ SUSPEND (reason: X late payments)
         │ NO
         ▼
    ┌──────────────────────┐
    │ 30+ days average late│
    └────┬────────────────┘
         │ YES
         └──→ ✅ SUSPEND (reason: High-risk pattern)
         │ NO
         ▼
    ❌ DO NOT SUSPEND
```

### Suspension Criteria Details

| Criteria | Trigger | Priority |
|----------|---------|----------|
| **VIP Status** | `customer.is_vip = True` | Blocks all suspensions |
| **Grace Period** | Today ≤ `customer.grace_payment_date` | Blocks all suspensions |
| **Overdue Invoices** | `invoices.status = 'unpaid' OR 'overdue'` AND `due_date < now()` | High Priority |
| **Missed Payments** | 2+ unpaid/overdue invoices past due | High Priority |
| **Late Payments** | 3+ invoices paid after due date | Medium Priority |
| **High-Risk Pattern** | Average days late > 30 | Medium Priority |

### Payment Pattern Analysis

When analyzing a customer's payment history:

**Metrics Calculated (from 6-month history):**
- `on_time_payment_count` - Invoices paid on or before due date
- `late_payment_count` - Invoices paid after due date
- `missed_payment_count` - Invoices still unpaid past due date
- `avg_days_late` - Average days late on late payments
- `avg_payment_amount` - Average payment size
- `is_risky` - Boolean flag set if customer meets risky criteria

**Risk Classification:**
```
is_risky = TRUE if ANY of:
  - missed_payment_count >= 2
  - late_payment_count >= 3
  - avg_days_late > 30 days
```

### Grace Period Logic

Grace period is a day-of-month feature:

```python
# If today's day-of-month <= grace_payment_date
# Then customer is protected from suspension

Example:
  grace_payment_date = 15
  Today = Dec 10  → Protected (10 <= 15)
  Today = Dec 20  → Not protected (20 > 15)
```

The logic allows customers to make payments up to a certain day of the month without triggering suspension.

---

## API Endpoints

### 1. List Suspensions
**GET** `/suspensions/`

**Purpose:** Display all suspension records with filtering

**Query Parameters:**
- `page` (int, default=1) - Pagination
- `filter` (str, default='all') - Filter type: `all`, `active`, `resolved`, `candidates`

**Response:** Renders `suspensions/list.html` with:
- Suspension records paginated (50 per page)
- Filtered by suspension status
- Ordered by suspension date (newest first)

**Database Query:**
```python
Suspension.query
  .filter_by(is_active=True/False)
  .order_by(Suspension.suspension_date.desc())
  .paginate(page=page, per_page=50)
```

---

### 2. View Suspension Candidates
**GET** `/suspensions/candidates`

**Purpose:** Identify customers who should be suspended but aren't yet

**Query Parameters:**
- `page` (int, default=1) - Pagination

**Logic Flow:**
1. Get all active customers from database
2. For each customer, call `handler.should_suspend_service(customer)`
3. If should suspend AND not already suspended → add to candidates list
4. Build list with: `{customer, reason, patterns}`
5. Paginate manually (50 per page)

**Response:** Renders `suspensions/candidates.html` with:
- List of customers eligible for suspension
- Reason why they're eligible
- Their payment patterns
- Pagination controls

**Key Code:**
```python
candidates = []
for customer in customers:
    should_suspend, reason = handler.should_suspend_service(customer)

    if should_suspend:
        existing = Suspension.query.filter_by(
            customer_id=customer.id,
            is_active=True
        ).first()

        if not existing:  # Not already suspended
            candidates.append({
                'customer': customer,
                'reason': reason,
                'patterns': PaymentPattern.query.filter_by(
                    customer_id=customer.id
                ).first()
            })
```

---

### 3. Customer Suspension Details
**GET** `/suspensions/customer/<customer_id>`

**Purpose:** View detailed suspension information for one customer

**Path Parameters:**
- `customer_id` (int) - Customer database ID

**Database Queries:**
```python
Customer.query.filter_by(id=customer_id)
Suspension.query.filter_by(customer_id=customer_id)
PaymentPattern.query.filter_by(customer_id=customer_id)
Invoice.query.filter_by(customer_id=customer_id).limit(10)
Service.query.filter_by(customer_id=customer_id)
```

**Response:** Renders `suspensions/customer_details.html` with:
- Customer header (name, balance, status, VIP)
- Suspension eligibility assessment
- Active/resolved suspensions history
- Services (with suspend button if eligible)
- Payment pattern analysis chart
- Recent invoices (last 10)
- Refresh & navigation buttons

**Frontend Logic in Template:**
- Show red alert if should suspend
- Show green alert if doesn't meet criteria
- Disable suspend buttons if not eligible
- Show suspension reasons
- Display payment pattern visuals

---

### 4. Suspend Service (API)
**POST** `/suspensions/api/suspend`

**Purpose:** Create a suspension and suspend service in UISP

**Request Body (JSON):**
```json
{
  "customer_id": 1,
  "service_id": 1,
  "reason": "Non-payment",
  "note": "Optional note",
  "grace_override": false
}
```

**Validation:**
- Customer & service must exist
- Customer must meet suspension criteria (unless `grace_override=true`)
- Both IDs must be provided

**API Call Chain:**
1. **Validate** customer & service exist
2. **Check** suspension criteria via `handler.should_suspend_service()`
3. **UISP Call** → `handler.suspend_service_uisp(service.uisp_service_id)`
4. **Create** Suspension record in database
5. **Update** Service status to 'suspended'
6. **Audit Log** via `log_user_activity()`

**UISP API Call Made:**
```
PATCH https://uisp-ros1.afrieta.com/crm/api/v2.0/services/{service_id}
Headers: {'X-Auth-App-Key': API_KEY, 'Content-Type': 'application/json'}
Body: {'status': '3'}  # 3 = suspended
```

**Response (Success - 201):**
```json
{
  "status": "success",
  "message": "Service suspended successfully",
  "suspension_id": 123
}
```

**Response (Error - 400/500):**
```json
{
  "error": "Error message here"
}
```

**Database Changes:**
```python
# Create suspension record
suspension = Suspension(
    customer_id=customer_id,
    uisp_service_id=service_id,
    suspension_reason=reason,
    suspended_by=username,
    note=note,
    is_active=True,
    suspension_date=now()  # Auto-set
)

# Update service
service.status = 'suspended'

# Log activity
log_user_activity(
    user_id=current_user.id,
    username=current_user.username,
    action='SUSPEND_SERVICE',
    details=f'...',
    ip_address=request.remote_addr,
    user_agent=request.headers.get('User-Agent'),
    endpoint=request.path,
    method=request.method
)
```

---

### 5. Reactivate Service (API)
**POST** `/suspensions/api/reactivate`

**Purpose:** Reactivate a suspended service

**Request Body (JSON):**
```json
{
  "suspension_id": 123,
  "note": "Optional reactivation note"
}
```

**Validation:**
- Suspension must exist
- Suspension must be active (`is_active=True`)

**API Call Chain:**
1. **Fetch** suspension record
2. **Validate** suspension is active
3. **UISP Call** → `handler.reactivate_service_uisp(service_id)`
4. **Update** suspension record: set `is_active=False`, add `reactivation_date`
5. **Update** service status to 'active'
6. **Audit Log**

**UISP API Call Made:**
```
PATCH https://uisp-ros1.afrieta.com/crm/api/v2.0/services/{service_id}
Headers: {'X-Auth-App-Key': API_KEY, 'Content-Type': 'application/json'}
Body: {'status': '1'}  # 1 = active
```

**Response (Success - 200):**
```json
{
  "status": "success",
  "message": "Service reactivated successfully"
}
```

**Database Changes:**
```python
suspension.is_active = False
suspension.reactivation_date = datetime.now(timezone.utc)
suspension.reactivated_by = username
suspension.note = note  # Append to existing

service.status = 'active'

log_user_activity(
    action='REACTIVATE_SERVICE',
    details=f'Reactivated service {service_id}...',
    ...
)
```

---

### 6. Bulk Suspend (API)
**POST** `/suspensions/api/bulk_suspend`

**Purpose:** Suspend multiple services in one operation

**Request Body (JSON):**
```json
{
  "suspensions": [
    {
      "customer_id": 1,
      "service_id": 1,
      "reason": "Non-payment"
    },
    {
      "customer_id": 2,
      "service_id": 2,
      "reason": "Non-payment"
    }
  ]
}
```

**Logic:**
- Loops through each suspension request
- Attempts each one independently
- Collects successes and failures
- Returns summary with results

**Return Value:**
```json
{
  "status": "completed",
  "success_count": 2,
  "failed_count": 0,
  "results": {
    "success": [
      {"customer_id": 1, "service_id": 1, "suspension_id": 123},
      {"customer_id": 2, "service_id": 2, "suspension_id": 124}
    ],
    "failed": []
  }
}
```

**Single Suspension Audit:**
- Each successful suspension logs a SUSPEND_SERVICE action
- Bulk action logs a separate BULK_SUSPEND_SERVICES action with count summary

---

### 7. Refresh Customer Cache (API)
**POST** `/suspensions/api/refresh_customer/<customer_id>`

**Purpose:** Fetch latest data from UISP and update local cache

**Path Parameters:**
- `customer_id` (int) - Customer database ID

**UISP API Calls Made (in sequence):**

**Call 1: Fetch Customer Data**
```
GET https://uisp-ros1.afrieta.com/crm/api/v2.1/clients/{uisp_client_id}
```
Returns:
- Customer name, email, balance
- VIP attribute (key='vip')
- Grace payment date attribute (key='gracePaymentDate')
- Active status
- Contact information
- Has overdue invoice flag

**Call 2: Fetch Services**
```
GET https://uisp-ros1.afrieta.com/crm/api/v2.0/clients/services?clientId={id}&statuses[]=1
```
Returns: List of active services with:
- Service ID
- Service name
- Status
- Billing amount

**Call 3: Fetch Invoices (6 months)**
```
GET https://uisp-ros1.afrieta.com/crm/api/v1.0/invoices?
  clientId={id}&
  createdDateFrom=2025-06-14&
  createdDateTo=2025-12-14&
  limit=1000
```
Returns: List of invoices with:
- Invoice number
- Amounts (total, remaining)
- Status (paid, unpaid, overdue, etc.)
- Dates (created, due)

**Call 4: Fetch Payments (6 months)**
```
GET https://uisp-ros1.afrieta.com/crm/api/v1.0/payments?
  clientId={id}&
  createdDateFrom=2025-06-14&
  createdDateTo=2025-12-14&
  limit=1000
```
Returns: List of payments with:
- Payment amount
- Payment method
- Payment date

**Call 5: Analyze Payment Pattern**
- No UISP call (local calculation)
- Analyzes cached invoices & payments
- Updates `PaymentPattern` record
- Recalculates risk metrics

**Response (Success - 200):**
```json
{
  "status": "success",
  "message": "Customer cache refreshed",
  "cached_at": "2025-12-14T12:34:56.789123"
}
```

**Database Changes:**
- All customer data updated (last_name, email, etc.)
- `cached_at` timestamp set to now
- All services updated/inserted
- All invoices updated/inserted (last 6 months)
- All payments updated/inserted (last 6 months)
- Payment pattern recalculated

**Audit Log:**
```
action='REFRESH_CUSTOMER_CACHE'
details=f'Refreshed cached data for customer {uisp_client_id}'
```

---

### 8. Dashboard Statistics (API)
**GET** `/suspensions/api/dashboard`

**Purpose:** Get summary statistics for dashboard display

**Database Queries:**
```python
Suspension.query.filter_by(is_active=True).count()
Suspension.query.filter(is_active=False, reactivation_date!=None).count()
Customer.query.filter_by(is_vip=True).count()
Customer.query.filter_by(has_overdue_invoice=True).count()
PaymentPattern.query.filter_by(is_risky=True).count()
Service.query.filter_by(status='active').count()
Service.query.filter_by(status='suspended').count()

# Recent suspensions (last 30 days)
Suspension.query.filter(suspension_date >= now() - 30 days).count()
```

**Response (Success - 200):**
```json
{
  "active_suspensions": 5,
  "resolved_suspensions": 2,
  "vip_customers": 3,
  "customers_with_overdue": 12,
  "risky_patterns": 8,
  "active_services": 45,
  "suspended_services": 5,
  "recent_suspensions": 2
}
```

---

## UISP Integration

### Base Configuration

```python
BASE_URL = "https://uisp-ros1.afrieta.com/crm/api/"
API_KEY = Config.UISP_API_KEY  # From .env
Headers = {
    'X-Auth-App-Key': API_KEY,
    'Content-Type': 'application/json'
}
Timeout = 30 seconds
```

### UISP API Versions Used

| Endpoint | Version | Purpose |
|----------|---------|---------|
| `/clients/{id}` | v2.1 | Fetch customer details |
| `/clients/services` | v2.0 | List customer services |
| `/invoices` | v1.0 | Fetch invoice history |
| `/payments` | v1.0 | Fetch payment history |
| `/services/{id}` | v2.0 | Suspend/reactivate service |

### Data Mapping

**Customer Attributes:**
```python
# UISP → Local Database
client_data.get('firstName')           → customer.first_name
client_data.get('lastName')            → customer.last_name
client_data.get('username')            → customer.email
client_data.get('accountBalance')      → customer.account_balance
client_data.get('accountOutstanding')  → customer.account_outstanding
client_data.get('accountCredit')       → customer.account_credit
client_data.get('isActive')            → customer.is_active
client_data.get('hasOverdueInvoice')   → customer.has_overdue_invoice
client_data.get('fullAddress')         → customer.address

# Custom Attributes (from attributes array)
attributes[key='vip'].value            → customer.is_vip (0 or 1)
attributes[key='gracePaymentDate'].value → customer.grace_payment_date
```

**Service Status Mapping:**
```python
{
  1: 'active',
  2: 'prepared',
  3: 'suspended',
  4: 'quoted',
}
```

**Invoice Status Mapping:**
```python
{
  'draft': 'draft',
  'issued': 'issued',
  'unpaid': 'unpaid',
  'overdue': 'overdue',
  'paid': 'paid',
  'cancelled': 'cancelled',
}
```

### Error Handling

All UISP API calls:
- Have 30-second timeout
- Catch `RequestException`
- Log errors to logger
- Return `None` on failure
- Allow application to continue (graceful degradation)

```python
except requests.exceptions.RequestException as e:
    logger.error(f"UISP API request failed: {method} {endpoint} - {str(e)}")
    return None
```

---

## Web UI Interactions

### Frontend JavaScript Functions

All frontend interactions use `fetch()` API with JSON.

#### Function: suspendService()
**Triggered By:** "Suspend" button on customer details page

```javascript
function suspendService(customerId, serviceId, reason) {
    const note = prompt('Enter suspension note (optional):');

    fetch('/suspensions/api/suspend', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            customer_id: customerId,
            service_id: serviceId,
            reason: reason,
            note: note || ''
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            alert('Service suspended successfully');
            location.reload();
        } else {
            alert('Error: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to suspend service');
    });
}
```

**Flow:**
1. User clicks "Suspend" button
2. Prompt user for optional note
3. POST to `/suspensions/api/suspend`
4. Show success/error alert
5. Reload page if successful

#### Function: reactivateService()
**Triggered By:** "Reactivate" button on suspension history

```javascript
function reactivateService(suspensionId) {
    if (!confirm('Are you sure you want to reactivate this service?')) {
        return;
    }

    const note = prompt('Enter reactivation note (optional):');

    fetch('/suspensions/api/reactivate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            suspension_id: suspensionId,
            note: note || ''
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            alert('Service reactivated successfully');
            location.reload();
        } else {
            alert('Error: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to reactivate service');
    });
}
```

**Flow:**
1. User clicks "Reactivate" button
2. Confirm action
3. Prompt for optional note
4. POST to `/suspensions/api/reactivate`
5. Show success/error alert
6. Reload page if successful

#### Function: refreshCache()
**Triggered By:** "Refresh from UISP" button on customer details page

```javascript
function refreshCache() {
    if (!confirm('Refresh customer data from UISP? This may take a moment.')) {
        return;
    }

    fetch('/suspensions/api/refresh_customer/<customer_id>', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            alert('Customer data refreshed from UISP');
            location.reload();
        } else {
            alert('Error: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to refresh customer data');
    });
}
```

**Flow:**
1. User clicks "Refresh from UISP" button
2. Confirm action
3. POST to `/suspensions/api/refresh_customer/<id>`
4. UISP handler fetches fresh data
5. Show success/error alert
6. Reload page if successful

### UI Display Logic

**Customer Details Template Flow:**

1. **Header Section**
   - Customer name
   - Outstanding balance (color-coded)
   - Account status (green=active, red=inactive)
   - VIP status

2. **Suspension Eligibility Alert**
   - RED alert if `should_suspend == True` (shows reason)
   - GREEN alert if `should_suspend == False` (shows why not)

3. **Suspension History**
   - Lists all suspensions (active & resolved)
   - Shows suspension date, reason, who suspended it
   - Shows reactivation date if resolved
   - "Reactivate" button only on active suspensions

4. **Services Table**
   - Lists all services for customer
   - Status column (color-coded badges)
   - "Suspend" button only if:
     - Service is active
     - Customer meets suspension criteria

5. **Payment Pattern Section**
   - On-time payment count (green)
   - Late payment count (orange)
   - Missed payment count (red)
   - Average days late
   - Risk level (HIGH RISK in red, LOW RISK in green)
   - Last payment date

6. **Recent Invoices Table**
   - Last 10 invoices
   - Amount, due date, status
   - Overdue indicator (in red) if past due & not paid

7. **Action Buttons**
   - "Refresh from UISP" - syncs fresh data
   - "Back to Candidates" - navigation

### Conditional Rendering Rules

| Condition | Result |
|-----------|--------|
| VIP = True | Show "VIP" badge, no suspend button |
| Within grace period | Show grace period message, no suspend button |
| Has overdue invoices | Show red alert, enable suspend button |
| Risky payment pattern | Show red alert, enable suspend button |
| Already suspended | Show ACTIVE badge, show reactivate button |
| No active suspension | Hide reactivation buttons |

---

## Database Schema

### Related Tables

#### Customers
```sql
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    uisp_client_id INTEGER UNIQUE,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    account_balance REAL DEFAULT 0.0,
    account_outstanding REAL DEFAULT 0.0,
    account_credit REAL DEFAULT 0.0,
    is_active BOOLEAN DEFAULT TRUE,
    has_overdue_invoice BOOLEAN DEFAULT FALSE,
    is_vip BOOLEAN DEFAULT FALSE,
    grace_payment_date INTEGER,  -- Day of month (1-31)
    cached_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Suspensions
```sql
CREATE TABLE suspensions (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    uisp_service_id INTEGER NOT NULL,
    suspension_reason TEXT,
    suspended_by TEXT,
    suspended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    reactivated_by TEXT,
    reactivation_date TIMESTAMP,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(customer_id) REFERENCES customers(id)
);
```

#### PaymentPatterns
```sql
CREATE TABLE payment_patterns (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL UNIQUE,
    on_time_payment_count INTEGER DEFAULT 0,
    late_payment_count INTEGER DEFAULT 0,
    missed_payment_count INTEGER DEFAULT 0,
    avg_days_late REAL,
    avg_payment_amount REAL,
    last_payment_date TIMESTAMP,
    is_risky BOOLEAN DEFAULT FALSE,
    analysis_period_start TIMESTAMP,
    analysis_period_end TIMESTAMP,
    calculated_at TIMESTAMP,
    FOREIGN KEY(customer_id) REFERENCES customers(id)
);
```

#### Invoices
```sql
CREATE TABLE invoices (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    uisp_invoice_id INTEGER UNIQUE,
    invoice_number TEXT,
    total_amount REAL DEFAULT 0.0,
    remaining_amount REAL DEFAULT 0.0,
    status TEXT,
    created_date TIMESTAMP,
    due_date TIMESTAMP,
    cached_at TIMESTAMP,
    FOREIGN KEY(customer_id) REFERENCES customers(id)
);
```

#### Services
```sql
CREATE TABLE services (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    uisp_service_id INTEGER UNIQUE,
    service_name TEXT,
    status TEXT DEFAULT 'active',
    billing_amount REAL,
    cached_at TIMESTAMP,
    FOREIGN KEY(customer_id) REFERENCES customers(id)
);
```

#### CachedPayments
```sql
CREATE TABLE cached_payments (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    uisp_payment_id TEXT UNIQUE,
    amount REAL DEFAULT 0.0,
    method TEXT,
    note TEXT,
    created_date TIMESTAMP,
    cached_at TIMESTAMP,
    FOREIGN KEY(customer_id) REFERENCES customers(id)
);
```

---

## Code Location Reference

### Flask Routes
**File:** `app/suspension_routes.py` (441 lines)

| Route | Method | Lines | Purpose |
|-------|--------|-------|---------|
| `/` | GET | 21-41 | List suspensions |
| `/candidates` | GET | 44-91 | View candidates |
| `/customer/<id>` | GET | 94-130 | Customer details |
| `/api/suspend` | POST | 133-211 | Suspend service |
| `/api/reactivate` | POST | 214-273 | Reactivate service |
| `/api/bulk_suspend` | POST | 276-367 | Bulk suspend |
| `/api/refresh_customer/<id>` | POST | 370-406 | Refresh cache |
| `/api/dashboard` | GET | 409-440 | Dashboard stats |

### UISP Handler
**File:** `app/uisp_suspension_handler.py` (479 lines)

| Method | Lines | Purpose |
|--------|-------|---------|
| `_make_request()` | 32-48 | Generic HTTP request |
| `fetch_and_cache_client()` | 50-113 | Get customer from UISP |
| `fetch_and_cache_services()` | 115-167 | Get services from UISP |
| `fetch_and_cache_invoices()` | 169-235 | Get invoices from UISP |
| `fetch_and_cache_payments()` | 237-304 | Get payments from UISP |
| `analyze_payment_pattern()` | 306-382 | Calculate risk metrics |
| `should_suspend_service()` | 384-418 | Determine suspension eligibility |
| `suspend_service_uisp()` | 420-437 | Call UISP suspend API |
| `reactivate_service_uisp()` | 439-456 | Call UISP reactivate API |
| `_map_service_status()` | 458-466 | Map status codes |
| `_map_invoice_status()` | 468-478 | Map invoice status |

### Models
**File:** `app/models.py` (extended)

New models added:
- `Customer`
- `Service`
- `Invoice`
- `CachedPayment`
- `Suspension`
- `PaymentPattern`

### Templates
**File:** `app/templates/suspensions/`

| Template | Purpose |
|----------|---------|
| `list.html` | List all suspensions |
| `candidates.html` | List suspension candidates |
| `customer_details.html` | Customer detail view |

### Migration
**File:** `scripts/migrate_suspension_tables.py`

Creates all 6 suspension-related tables with indexes.

---

## Summary

The suspension feature operates as follows:

1. **User Interface** - Web pages display customers and suspension status
2. **Decision Logic** - Payment history analysis determines suspension eligibility
3. **API Integration** - Endpoints handle suspend/reactivate operations
4. **UISP Sync** - Regular data refresh keeps local cache current
5. **Audit Trail** - All actions logged for compliance
6. **Smart Features** - VIP protection, grace periods, pattern analysis

All operations are protected by:
- Login requirement (`@login_required`)
- Database transaction rollback on error
- Try/catch blocks around external API calls
- Comprehensive audit logging
- User activity tracking

---

**Document Version:** 1.0
**Last Updated:** 2025-12-14
**Status:** Complete & Comprehensive
