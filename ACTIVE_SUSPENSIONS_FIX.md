# Active Suspensions Filter - Fixed to Use UISP API

**Date:** 2025-12-14
**Status:** Fixed & Ready to Test
**File:** ACTIVE_SUSPENSIONS_FIX.md

---

## Problem

The "Active Suspensions" tab showed nothing because it was only looking at local database records, not checking UISP for actual suspended services.

## Solution

Changed to fetch **directly from UISP API** using the endpoint you provided:
```
GET crm/api/v1.0/clients/services?statuses[]=3
```

This endpoint returns **all services with status=3 (suspended)** from UISP, regardless of whether they have a record in our local database.

---

## Changes Made

### 1. Added New Method to UISP Handler
**File:** `app/uisp_suspension_handler.py` (lines 458-486)

```python
def fetch_suspended_services(self) -> List[Dict]:
    """Fetch all suspended services (status=3) from UISP for all customers."""
```

**What it does:**
- Calls: `GET v1.0/clients/services?statuses[]=3`
- Returns: All suspended services from UISP
- Handles both list and dict response formats
- Returns empty list on error (graceful degradation)

### 2. Updated List Suspensions Route
**File:** `app/suspension_routes.py` (lines 21-158)

**Before:**
- Looked only at Suspension table records
- Checked `is_active=True` flag
- Showed nothing if no local records

**After:**
- When `filter=active` is selected
- Calls `handler.fetch_suspended_services()`
- Fetches ALL suspended services from UISP (status=3)
- For each service:
  1. Gets the customer (from DB or UISP)
  2. Checks if we have a local suspension record
  3. If yes: Uses local record with UISP data
  4. If no: Creates pseudo-record from UISP data (marked as "External/UISP")

**Result:** Shows ALL services suspended in UISP, not just ones we created locally

### 3. Enhanced Template Display
**File:** `app/templates/suspensions/list.html` (lines 82-135)

**Changes:**
- Handles both DB records and UISP-only records
- Shows suspension date if available, or "From UISP (no local record)" if not
- Service names now always display
- Customer links work for both types
- More robust null checking

---

## How It Works Now

### When User Clicks "Active Suspensions":

```
1. Route: GET /suspensions/?filter=active
   ↓
2. Call: handler.fetch_suspended_services()
   ↓
3. UISP API: GET v1.0/clients/services?statuses[]=3
   ├─ Returns: All services with status=3
   └─ Example Response:
      [
        {
          "id": 12345,
          "clientId": 456,
          "serviceName": "Internet Connection",
          "billingAmount": 299.00,
          "status": 3
        },
        ...
      ]
   ↓
4. Process Each Service:
   ├─ Get Customer (ID: clientId)
   ├─ Look for local Suspension record
   └─ Build display object
   ↓
5. Display All Suspended Services:
   ├─ With UISP service details
   ├─ With customer info
   └─ Marked as UISP status=suspended
```

---

## Data Source Comparison

### Before Fix
| Data Source | Status |
|---|---|
| UISP | Checked? ❌ No |
| Local DB | Checked? ✅ Yes (only) |
| Result | Empty if no local records |

### After Fix
| Data Source | Status |
|---|---|
| UISP | Checked? ✅ Yes (primary source) |
| Local DB | Checked? ✅ Yes (supplementary) |
| Result | Shows ALL suspended services |

---

## Three Types of Suspended Services Now Shown

### Type 1: Suspended via Our System
```
Scenario: User clicks "Suspend" button → Service suspended in UISP
Local Record: ✅ Yes (suspension_date, suspended_by, etc.)
UISP Record: ✅ Yes (status=3)
Display: Shows local suspension date & reason
Icon: ACTIVE (red) in database
```

### Type 2: Suspended Externally (Already in UISP)
```
Scenario: Service was suspended outside our system
Local Record: ❌ No (doesn't exist in our DB)
UISP Record: ✅ Yes (status=3)
Display: Shows "From UISP (no local record)"
Icon: ACTIVE (red) - marked as External/UISP
```

### Type 3: Suspended via Our System, Then Reactivated
```
Scenario: We suspended it, then it was reactivated
Local Record: ✅ Yes (but is_active=False, reactivation_date set)
UISP Record: ✅ No (status=1, back to active)
Display: Does NOT appear in active suspensions
Location: Appears in "Resolved Suspensions" tab instead
```

---

## API Call Flow

```
┌─────────────────────────────────────┐
│ User Clicks: Active Suspensions     │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ GET /suspensions/?filter=active      │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│ _get_active_suspensions_from_uisp() │
└────────────┬────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────┐
│ handler.fetch_suspended_services()         │
│ UISP API Call:                             │
│ GET v1.0/clients/services?statuses[]=3   │
└────────────┬─────────────────────────────┘
             │
             ├─ Returns: List of suspended services
             │
             ▼
┌────────────────────────────────────┐
│ For Each Suspended Service:        │
├────────────────────────────────────┤
│ 1. Get Customer (uisp_client_id)   │
│ 2. Check local Suspension record   │
│ 3. Build display object            │
│ 4. Add to results list             │
└────────────┬─────────────────────┘
             │
             ▼
┌────────────────────────────────────┐
│ Manual Pagination (50 per page)    │
└────────────┬─────────────────────┘
             │
             ▼
┌────────────────────────────────────┐
│ Render Template                    │
│ Show all suspended services        │
└────────────────────────────────────┘
```

---

## Testing the Fix

### Test 1: View Active Suspensions
```bash
1. Go to: /suspensions/?filter=active
2. Expected: Shows list of suspended services from UISP
3. Should include:
   ✅ Service ID
   ✅ Service Name
   ✅ Customer Name & CID
   ✅ UISP: SUSPENDED status
   ✅ Suspension Reason (if in our DB)
   ✅ Suspended By (if in our DB)
```

### Test 2: Services Suspended Only in UISP
```bash
1. Go to UISP and suspend a service manually (not via our app)
2. Go to: /suspensions/?filter=active
3. Expected: Service appears with label "From UISP (no local record)"
4. Verify:
   ✅ Service details show correctly
   ✅ Customer is fetched and cached
   ✅ Not marked with a local suspension date
```

### Test 3: Services We Suspended
```bash
1. Go to: /suspensions/candidates
2. Click "Suspend" on a service
3. Go to: /suspensions/?filter=active
4. Expected: Service appears with full details
5. Verify:
   ✅ Shows suspension date/time
   ✅ Shows who suspended it
   ✅ Shows suspension reason
   ✅ Reactivate button available
```

### Test 4: Pagination
```bash
1. Have more than 50 suspended services
2. Go to: /suspensions/?filter=active
3. Expected: Shows page 1 of N
4. Verify:
   ✅ Next/Previous buttons work
   ✅ Correct 50 services per page
```

---

## Files Modified

| File | Lines | Changes |
|------|-------|---------|
| `app/uisp_suspension_handler.py` | 458-486 | Added `fetch_suspended_services()` method |
| `app/suspension_routes.py` | 21-158 | Rewrote `list_suspensions()` and added `_get_active_suspensions_from_uisp()` |
| `app/templates/suspensions/list.html` | 82-135 | Enhanced template for UISP-only records |

---

## Error Handling

**If UISP API call fails:**
- Logs error to application logs
- Returns empty page with "No suspensions found" message
- Does NOT crash the application
- User can refresh to retry

**If customer not found in UISP:**
- Service is skipped (not displayed)
- Not added to results
- Logged as warning

**If customer not in local DB:**
- Fetches from UISP and caches locally
- Then displays normally
- Future requests use cached version

---

## Performance Considerations

### Before Fix
- Database query: Fast (1 query)
- API calls: None
- Shows: Only local records

### After Fix
- Database queries: Multiple (per service found)
- API calls: 1 main call + potentially N customer fetch calls
- Shows: All suspended services from UISP

**Optimization:** Consider caching the UISP response for 15 minutes if performance becomes an issue.

---

## Known Limitations

1. **One-way sync only** - Displays UISP data but doesn't create local records automatically
   - Solution: User can still interact with "Create suspension" functionality

2. **No automatic cleanup** - If service is reactivated in UISP, our local record stays `is_active=True`
   - Workaround: User can manually click Reactivate to update local record

3. **Performance with many suspensions** - If thousands of services suspended, pagination needed
   - Current: 50 per page (configurable)

---

## Future Enhancements

1. **Auto-sync** - Periodically sync UISP suspended services with local DB
2. **Bulk Import** - Button to create local records for externally suspended services
3. **Status Reconciliation** - Alert if local status doesn't match UISP
4. **Dashboard Widget** - Show active suspension count in real-time
5. **Export** - Download active suspensions as CSV/PDF

---

## Configuration

To change items per page, edit line 113 in `app/suspension_routes.py`:
```python
per_page = 50  # Change to desired number
```

---

## Summary

The "Active Suspensions" filter now:
- ✅ Shows ALL suspended services from UISP (status=3)
- ✅ Includes services we suspended locally
- ✅ Includes services suspended externally
- ✅ Displays complete service details
- ✅ Shows customer information
- ✅ Indicates data source (local vs UISP-only)
- ✅ Works with pagination
- ✅ Gracefully handles errors

**Result:** Users can now see the actual state of suspended services in UISP!

---

**Document Version:** 1.0
**Status:** Ready to Test
**Next Step:** Restart application and test with actual UISP data
