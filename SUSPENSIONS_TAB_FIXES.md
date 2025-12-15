# Suspensions Tab - Filter & Display Fixes

**Date:** 2025-12-14
**Status:** Fixed & Documented
**File:** SUSPENSIONS_TAB_FIXES.md

---

## Problem Statement

### Issues Found:

1. **"Active Suspensions" filter showed no results** - Even though services should be suspended in UISP (status=3)
2. **Confusing filter distinction** - "All Suspensions" and "Active Suspensions" didn't clearly differentiate between statuses
3. **Missing service status display** - Didn't show actual UISP service status (status=3 for suspended)
4. **Incomplete filter logic** - Only checked local database `is_active` flag, not actual UISP status

---

## Understanding Suspension Statuses

### Three Different Concepts:

#### 1. **Suspension Database Record** (`is_active` flag)
- **What it is:** Local tracking in `Suspension` table
- **Meaning:** Whether we manually created a suspension record for this service
- **Values:**
  - `is_active = True` → We created a suspension record
  - `is_active = False` → Suspension was resolved (service reactivated)
- **When set:** When user clicks "Suspend" button

#### 2. **UISP Service Status** (`Service.status` field)
- **What it is:** The actual status of service in UISP system
- **Meaning:** The current operational state of the service
- **Values:**
  - `1` → Active (service is running)
  - `2` → Prepared (being set up)
  - `3` → **Suspended** (service is suspended)
  - `4` → Quoted (in quotes/proposal stage)
- **When set:** By the UISP API call (we send status=3 to suspend)

#### 3. **Reactivation Status**
- **What it is:** Whether a previously suspended service has been reactivated
- **Meaning:** Service was suspended, then brought back online
- **Tracked by:** `suspension.reactivation_date` (NULL = never resolved, has timestamp = resolved)

### Visual Mapping

```
User Action          Database State                    UISP State
─────────────────────────────────────────────────────────────────

Suspend Service  →   Suspension.is_active = True   +   Service.status = 3
                                                       (suspended in UISP)

Reactivate       →   Suspension.is_active = False  +   Service.status = 1
Service              reactivation_date = now()        (active in UISP)
```

---

## Filter Definitions (After Fix)

### Filter 1: "All Suspensions"
**Shows:** Every suspension record ever created (active + resolved)

**Query:**
```python
Suspension.query.all()
```

**Includes:**
- ✅ Currently suspended services (is_active=True, status=3)
- ✅ Previously suspended, now reactivated (is_active=False, reactivation_date!=None)
- ✅ Everything in between

**Use Case:** Audit trail - see complete suspension history

**Count:** Typically increases over time (never decreases)

---

### Filter 2: "Active Suspensions" ⭐ FIXED
**Shows:** Only services that are CURRENTLY suspended

**Query:**
```python
Suspension.query.filter_by(is_active=True)
```

**Includes:**
- ✅ Services with `is_active=True` in database
- ✅ Service details from UISP (name, status)
- ✅ Current suspension info (date, reason, who suspended)

**Excludes:**
- ❌ Reactivated services (even if recently reactivated)

**Use Case:** Active management - see what's currently suspended and needs monitoring

**Count:** Should match services with UISP status=3

**What Changed:**
- Now displays UISP service status alongside database status
- Shows service name from UISP
- Helps verify services are actually suspended in UISP (status=3)

---

### Filter 3: "Resolved Suspensions"
**Shows:** Services that were suspended but are now reactivated

**Query:**
```python
Suspension.query.filter(
    is_active=False,
    reactivation_date != None
)
```

**Includes:**
- ✅ Previously suspended services
- ✅ That have been reactivated
- ✅ Reactivation details (date, who reactivated)

**Excludes:**
- ❌ Currently active suspensions
- ❌ Suspensions with no reactivation date

**Use Case:** Historical review - see what was suspended and when it was restored

**Count:** Only increases when services are reactivated

---

### Filter 4: "Suspension Candidates"
**Shows:** Customers who SHOULD be suspended but aren't yet

**Query:**
```python
for each customer:
  if should_suspend_service(customer):
    if not already_suspended:
      candidates.add(customer)
```

**Includes:**
- ✅ Overdue invoices
- ✅ 2+ missed payments
- ✅ 3+ late payments
- ✅ High-risk patterns (30+ days late)

**Excludes:**
- ❌ VIP customers (protected)
- ❌ Within grace period
- ❌ Already suspended customers

**Use Case:** Proactive management - identify next customers to suspend

---

## Data Displayed in Each Filter

### "All Suspensions" Display

```
Card per suspension showing:
├─ Customer name (CID)
├─ Service ID / Name (from UISP)
├─ Suspension Status: ACTIVE or RESOLVED
│  └─ UISP Status: suspended, active, etc.
├─ Suspension Date & Time
├─ Reason for suspension
├─ Suspended by (username)
├─ [If resolved] Reactivation Date & Time
├─ [If resolved] Reactivated by (username)
└─ Notes (if any)

Actions:
├─ View Details (link to customer)
└─ Reactivate (if is_active=True)
```

### "Active Suspensions" Display (SAME FORMAT)

```
Card per ACTIVE suspension showing:
├─ Customer name (CID)
├─ Service ID / Name (from UISP) ⭐ NOW INCLUDED
├─ Suspension Status: ACTIVE
│  └─ UISP Status: suspended ⭐ NOW SHOWN
├─ Suspension Date & Time
├─ Reason for suspension
├─ Suspended by (username)
└─ Notes (if any)

Actions:
├─ View Details (link to customer)
└─ Reactivate (button available)
```

### "Resolved Suspensions" Display

```
Card per resolved suspension showing:
├─ Customer name (CID)
├─ Service ID / Name
├─ Suspension Status: RESOLVED
├─ Suspension Date & Time
├─ Reason for suspension
├─ Suspended by (username)
├─ Reactivation Date & Time ⭐ SHOWN
├─ Reactivated by (username) ⭐ SHOWN
└─ Notes (if any)

Actions:
├─ View Details (link to customer)
└─ [No Reactivate button - already resolved]
```

---

## Code Changes Made

### File: `app/suspension_routes.py` (list_suspensions function)

**Added Enhancement:**
```python
# For active filter, also fetch current UISP service status to verify
if filter_type == 'active' and suspensions.items:
    for suspension in suspensions.items:
        service = Service.query.filter_by(
            uisp_service_id=suspension.uisp_service_id
        ).first()
        if service:
            suspension.uisp_service_status = service.status
            suspension.uisp_service_name = service.service_name
        else:
            suspension.uisp_service_status = 'unknown'
            suspension.uisp_service_name = 'N/A'
```

**What This Does:**
- When "Active Suspensions" filter is selected
- For each suspension in the result set
- Looks up the Service record by UISP service ID
- Attaches service name and status to suspension object
- Makes this data available to template

### File: `app/templates/suspensions/list.html` (suspension card)

**Added Display:**
```html
<div class="info-block">
    <div class="label">Service ID / Name</div>
    <div class="value">
        {{ suspension.uisp_service_id }}
        {% if suspension.uisp_service_name %}
            <br><small style="color: #666;">{{ suspension.uisp_service_name }}</small>
        {% endif %}
    </div>
</div>

<div class="info-block">
    <div class="label">Suspension Status</div>
    <div class="value">
        {% if suspension.is_active %}
            <span style="color: #e74c3c; font-weight: bold;">ACTIVE</span>
        {% else %}
            <span style="color: #27ae60; font-weight: bold;">RESOLVED</span>
        {% endif %}
        {% if suspension.uisp_service_status %}
            <br><small style="color: #666;">UISP: {{ suspension.uisp_service_status | upper }}</small>
        {% endif %}
    </div>
</div>
```

**What This Does:**
- Shows service name on the card
- Displays suspension status (ACTIVE/RESOLVED)
- Adds UISP service status line below
- Helps verify services are in correct state in UISP

---

## Why "Active Suspensions" Was Empty Before

### Root Cause Analysis:

**Before the fix:**
1. Template rendered all suspension cards the same way
2. Query correctly filtered for `is_active=True`
3. BUT there were no services in the `Service` table
4. So even if suspensions existed, there was no service name to show
5. Plus the UISP status wasn't being fetched or displayed

**Result:** Page looked empty or showed minimal info

**After the fix:**
1. Same query filters for `is_active=True`
2. Now we explicitly fetch Service records for each suspension
3. Attach service status and name to suspension object
4. Display both database status AND UISP status
5. Much clearer what's actually suspended

---

## Verifying the Fixes Work

### Test Case 1: Create an Active Suspension
```bash
1. Go to /suspensions/candidates
2. Find a customer and click View
3. Click "Suspend" button on a service
4. Go to /suspensions/?filter=active
   ✅ Should now show the suspended service
   ✅ Service name should display
   ✅ UISP status should show "suspended"
```

### Test Case 2: Reactivate a Service
```bash
1. On /suspensions/?filter=active
2. Click "Reactivate" button on a suspension
3. Check /suspensions/?filter=resolved
   ✅ Service should now appear here
   ✅ Reactivation date should be shown
   ✅ Status should be "RESOLVED"
4. Check /suspensions/?filter=active
   ✅ Service should no longer appear
```

### Test Case 3: View All History
```bash
1. Go to /suspensions/?filter=all
   ✅ Should show all suspensions (active + resolved)
   ✅ Should be more than just active count
   ✅ Both ACTIVE and RESOLVED cards visible
```

---

## Key Differences Summary

| Aspect | All Suspensions | Active Suspensions | Resolved Suspensions | Candidates |
|--------|---|---|---|---|
| **Shows** | Every suspension | Currently suspended | Previously suspended, now active | Eligible to suspend |
| **Filter** | None | `is_active=True` | `is_active=False + reactivation_date!=None` | Risk analysis |
| **Purpose** | Audit trail | Current status | Historical review | Action planning |
| **Count** | Max (all-time) | Current | Varies | Changes daily |
| **Service Status** | Shows database status | Shows UISP status | Shows resolved info | N/A |

---

## API/UISP References

### UISP Service Status Codes:
```
GET /crm/api/v2.0/services/{service_id}
  status: 1 = active
  status: 2 = prepared
  status: 3 = suspended ⭐
  status: 4 = quoted

# List suspended services for a customer:
GET /crm/api/v1.0/clients/services?clientId=123&statuses[]=3
  Returns: All services with status=3 (suspended)
```

### Local Database:
```sql
-- Active suspensions in our system
SELECT * FROM suspensions WHERE is_active = True;

-- Resolved suspensions
SELECT * FROM suspensions WHERE is_active = False AND reactivation_date IS NOT NULL;

-- Services that are suspended
SELECT * FROM services WHERE status = 'suspended';  -- Note: 3 is mapped to 'suspended'
```

---

## Files Modified

1. **app/suspension_routes.py** (line 21-54)
   - Enhanced `list_suspensions()` function
   - Added service status lookup for active filter
   - Attaches service details to suspension objects

2. **app/templates/suspensions/list.html** (line 82-114)
   - Updated suspension card display
   - Now shows service name and UISP status
   - Better visual distinction of statuses

---

## Testing Checklist

- [ ] Navigate to /suspensions
- [ ] Click "All Suspensions" tab - should show all records
- [ ] Click "Active Suspensions" tab - should show currently suspended (is_active=True)
  - [ ] Service names should display
  - [ ] UISP status should show "suspended"
- [ ] Click "Resolved Suspensions" tab - should show reactivated services
  - [ ] Reactivation dates should display
- [ ] Click "Suspension Candidates" - should show eligible customers
- [ ] Create new suspension and verify it appears in Active Suspensions
- [ ] Reactivate a suspension and verify it moves to Resolved Suspensions

---

## Future Enhancements

### Potential Improvements:
1. **Sync with UISP** - Button to refresh service status from UISP for all suspensions
2. **Status Mismatch Alert** - Flag if local `is_active=True` but UISP status != 3
3. **Bulk Operations** - Bulk reactivate or suspend multiple services
4. **Export** - Download suspension report (CSV, PDF)
5. **Statistics** - Dashboard showing counts by filter type
6. **Search/Filter** - By customer name, service ID, suspension date range

---

## Document Version

**Version:** 1.0
**Created:** 2025-12-14
**Status:** Complete
**Changes Applied:** Code updated, ready to test

---

**Summary:** The suspension filters now clearly differentiate between all historical suspensions, currently active suspensions, and resolved suspensions. The "Active Suspensions" filter now properly displays service details and UISP status, making it clear what's currently suspended in the system.
