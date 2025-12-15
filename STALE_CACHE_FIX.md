# Stale Cache Data Fix - Active Suspensions

**Date:** 2025-12-14 03:54 UTC
**Status:** ✅ FIXED & DEPLOYED
**File:** STALE_CACHE_FIX.md

---

## Problem Identified

The "Active Suspensions" tab was showing CID 112 (Akbar Faruk Bhula) even though the customer was archived in UISP.

### Root Cause

The archived customer filter was checking **stale cached data** instead of **fresh data from UISP**.

**Timeline:**
1. **03:33:28** - CID 112 cached locally with `is_archived=False`
2. **Between 03:33:28 and 03:54:00** - Customer archived in UISP (`isArchived=True`)
3. **Before fix** - Route checked local cache which still said `is_archived=False`
4. **Result** - Service 1733 was displayed even though customer was archived

### Data Flow (Before Fix)

```
UISP API returns Service 1733 with clientId=112
    ↓
Query local DB for CID 112
    ↓
Get stale cached record (is_archived=False from 03:33:28)
    ↓
Filter doesn't catch it
    ↓
Service displays incorrectly ❌
```

---

## Solution Implemented

Always refresh customer data from UISP **before checking the archived status** in the active suspensions filter.

### Code Change

**File:** `app/suspension_routes.py`
**Lines:** 97-107
**Method:** `_get_active_suspensions_from_uisp()`

**Before:**
```python
# Get or create customer record
customer = Customer.query.filter_by(uisp_client_id=client_id).first()

if not customer:
    # Fetch customer from UISP if not in local DB
    customer = handler.fetch_and_cache_client(client_id)

if not customer:
    logger.warning(f"Could not fetch customer {client_id} for service {service_id}")
    continue  # Skip if customer not found

# Skip archived customers (CHECKING STALE DATA)
if customer.is_archived:
    logger.info(f"Skipping archived customer {client_id} for service {service_id}")
    continue
```

**After:**
```python
# Get or create customer record
customer = Customer.query.filter_by(uisp_client_id=client_id).first()

if not customer:
    # Fetch customer from UISP if not in local DB
    customer = handler.fetch_and_cache_client(client_id)

if not customer:
    logger.warning(f"Could not fetch customer {client_id} for service {service_id}")
    continue  # Skip if customer not found

# Always refresh customer data from UISP to get current archived status
# This prevents filtering out stale cached data
customer = handler.fetch_and_cache_client(client_id)
if not customer:
    logger.warning(f"Could not refresh customer {client_id} for service {service_id}")
    continue

# Skip archived customers (CHECKING FRESH DATA)
if customer.is_archived:
    logger.info(f"Skipping archived customer {client_id} for service {service_id}")
    continue
```

### Key Changes

1. **Added fresh data refresh** (lines 97-99)
   - Call `handler.fetch_and_cache_client(client_id)` again after initial fetch
   - This ensures we get the **current** archived status from UISP
   - Updates the local cache with fresh data

2. **Added error handling** (lines 100-102)
   - Handle case where UISP fetch fails on second attempt
   - Skip service if refresh fails

3. **Updated cache timestamp** (automatically)
   - When `fetch_and_cache_client()` is called, it updates `cached_at` timestamp
   - Previous timestamp: `03:33:28` (stale)
   - New timestamp: `03:52:35+` (fresh)

---

## Data Flow (After Fix)

```
UISP API returns Service 1733 with clientId=112
    ↓
Query local DB for CID 112
    ↓
REFRESH: Call fetch_and_cache_client(112) again
    ↓
Get fresh data from UISP
    ↓
Update local cache: is_archived=True (current)
    ↓
Filter catches it
    ↓
Service is skipped ✅
```

---

## Verification Results

### Before Fix
- **UISP Data:** Service 1733 belongs to CID 112 (isArchived=true)
- **Local Cache:** CID 112 with is_archived=False (stale)
- **Active Suspensions Displayed:** 17 services (WRONG - includes archived CID 112)

### After Fix
- **UISP Data:** Service 1733 belongs to CID 112 (isArchived=true)
- **Local Cache:** CID 112 with is_archived=True (refreshed)
- **Active Suspensions Displayed:** 16 services (CORRECT - excludes archived CID 112)

### Test Output

```
Services displayed (active customers): 16
Services skipped (archived customers): 1

ARCHIVED SERVICES (SKIPPED):
  Service 1733: Akbar Faruk Bhula (CID 112)

DISPLAYED SERVICES (16 total):
  1. Service 1673: Ayola Geca (CID 757)
  2. Service 1844: Elrise Botha (CID 700)
  3. Service 1947: Afikile Fubu (CID 878)
  4. Service 1979: Leshego Malema (CID 888)
  5. Service 2015: Akil Kazi (CID 449)
  6. Service 2246: Sibusiso Mazibuko (CID 981)
  7. Service 2309: Khanyiswa Stampu (CID 1008)
  8. Service 2355: Anotida Nicole Chido Potera (CID 1028)
  9. Service 2376: Gugu Mdletshe (CID 1047)
  10. Service 2543: Daleshney Scharnick (CID 1139)
  11. Service 2548: Bongani Mbelu (CID 1143)
  12. Service 2556: Ragel Josephine Kock (CID 1148)
  13. Service 2579: William Nhlapo (CID 1166)
  14. Service 2600: Anthea Scholtz (CID 900)
  15. Service 2601: Linda Perseverance Ngwenya (CID 1181)
  16. Service 2659: Kefilwe Victoria (CID 1222)
```

---

## Performance Impact

### API Calls
**Before:** 1 UISP API call to fetch suspended services + 0-17 calls to fetch customer data (cached if available)
**After:** 1 UISP API call to fetch suspended services + 17 calls to refresh customer data

**Impact:** +17 additional API calls per page view

### Mitigation Strategies

If performance becomes a concern, we can:

1. **Batch Refresh:** Fetch multiple customer records in one API call if UISP supports it
2. **Smart Refresh:** Only refresh if cache older than 1 hour (or configurable threshold)
3. **Background Job:** Periodically refresh customer archived status without blocking page load
4. **Separate View:** Create dedicated "Archived Services" view for admin purposes

### Current Status
- **Acceptable:** 17 additional calls per page load is acceptable for correctness
- **Response Time:** Typical 1-3 seconds (cached), max ~30 seconds (timeout)
- **Reliability:** Fallback to skip service if UISP fetch fails

---

## Deployment Timeline

| Time | Action |
|------|--------|
| 03:54:00 | Code deployed and application restarted |
| 03:54:05 | Verification tests run |
| 03:54:10 | Fix confirmed working |

---

## Monitoring

### Logs to Watch
```bash
# View archived customers being skipped
sudo journalctl -u fnb-web-gui.service | grep "Skipping archived"

# View UISP API calls
sudo journalctl -u fnb-web-gui.service | grep "fetch_and_cache_client"
```

### Expected Log Pattern
```
Skipping archived customer 112 for service 1733
```

### If Not Seeing Logs
- Service 1733 may not be in the suspended services list anymore
- Customer 112 may have been reactivated in UISP
- Check database for current state:
  ```python
  Customer.query.filter_by(uisp_client_id=112).first().is_archived
  ```

---

## Subsequent Considerations

### What if Customer Gets Reactivated?
1. User reactivates customer in UISP (sets isArchived=false)
2. Next time active suspensions page loads:
   - `fetch_and_cache_client(112)` gets updated data
   - Cache updated with `is_archived=False`
   - Filter passes
   - Service 1733 displays again

### What if Service Gets Reactivated in UISP?
1. Service status changes from 3 (suspended) to 1 (active)
2. `fetch_suspended_services()` won't return it anymore
3. Service won't appear on active suspensions list

### Database Cleanup
Currently, old cached data remains in database forever. Consider:
- Set cache TTL/expiration
- Implement cache cleanup job
- Archive old customer records

---

## Production Checklist

- ✅ Code deployed and tested
- ✅ Application restarted successfully
- ✅ Active suspensions count changed from 17 to 16
- ✅ CID 112 (Service 1733) now being skipped
- ✅ Remaining 16 services all from active customers
- ✅ No application errors in logs
- ✅ Ready for production use

---

## Summary

The stale cache data issue has been **FIXED** by implementing fresh data refresh before checking archived status.

**Key Points:**
1. **Root Cause:** Local cache had old archived=false status, UISP had updated to true
2. **Solution:** Refresh customer data from UISP before filtering
3. **Impact:** Service 1733 (CID 112) now correctly skipped
4. **Result:** Active suspensions showing correct count (16 instead of 17)
5. **Performance:** 17 additional API calls per page load (acceptable)

---

**Deployment Date:** 2025-12-14 03:54 UTC
**Status:** ✅ LIVE & VERIFIED
**Ready:** YES

