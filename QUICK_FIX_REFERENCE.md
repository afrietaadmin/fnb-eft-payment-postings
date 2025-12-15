# Quick Fix Reference - Stale Cache Data

**For:** Active Suspensions showing archived customers
**Status:** FIXED

---

## The Problem
Archived customers appearing in Active Suspensions list because filter checks stale cached data.

## The Fix
In `app/suspension_routes.py`, function `_get_active_suspensions_from_uisp()`:

**Add fresh data refresh before checking archived status:**

```python
# Always refresh customer data from UISP to get current archived status
customer = handler.fetch_and_cache_client(client_id)
if not customer:
    logger.warning(f"Could not refresh customer {client_id} for service {service_id}")
    continue
```

## Result
- Before: 17 services (includes archived customers)
- After: 16 services (excludes archived customers)

## Files Changed
1. `app/suspension_routes.py` - Lines 97-107

## How It Works
1. UISP returns list of suspended services with clientId
2. **OLD:** Query local DB, check is_archived from cache → STALE DATA
3. **NEW:** Query local DB → REFRESH from UISP → check fresh is_archived → CURRENT DATA
4. Skip if archived, display if active

## Verification
```bash
# Check if service 1733 (CID 112) is being skipped
./venv/bin/python3 -c "
from app import create_app, db
from app.models import Customer
from app.uisp_suspension_handler import UISPSuspensionHandler

app = create_app()
with app.app_context():
    handler = UISPSuspensionHandler()
    suspended = handler.fetch_suspended_services()
    for s in suspended:
        if s.get('id') == 1733:
            print(f'Service 1733 found, ClientId: {s.get(\"clientId\")}')
            c = handler.fetch_and_cache_client(s.get('clientId'))
            print(f'CID 112 is_archived: {c.is_archived}')
"
```

Expected output: `is_archived: True` (service should be skipped)

## Performance Trade-off
- **Before:** 1 UISP API call per page load
- **After:** 18 UISP API calls per page load (1 + 17)
- **Impact:** +17 calls, response time 1-3 seconds
- **Benefit:** Accuracy - no stale archived customers displayed

## Related Files
- Model: `app/models.py` (line 167 - is_archived field)
- Handler: `app/uisp_suspension_handler.py` (lines 87, 458-486)
- Documentation: `STALE_CACHE_FIX.md`

