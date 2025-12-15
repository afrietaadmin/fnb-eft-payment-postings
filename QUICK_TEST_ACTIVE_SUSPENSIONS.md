# Quick Test Guide - Active Suspensions Tab

**Status:** Ready to Test
**Date:** 2025-12-14 03:33 UTC

---

## What's New

The "Active Suspensions" tab now shows **ALL suspended services from UISP** (status=3), not just local database records.

---

## Quick Test (5 minutes)

### Step 1: Navigate to Active Suspensions
```
URL: http://localhost:8901/suspensions/?filter=active
```

### Step 2: What You Should See

If there ARE suspended services in UISP:
- List of suspended services
- Each card shows:
  * Customer name & ID
  * Service ID & Name
  * Status: ACTIVE (red)
  * UISP: SUSPENDED
  * Suspension reason (if local record exists)

If NO suspended services in UISP:
- Message: "No suspensions found"
- This is correct - there's nothing to suspend

### Step 3: Check Each Type of Suspension

#### Type A: Suspended via Our App
- Click "View Details" link
- Should take you to customer page
- Reactivate button should work

#### Type B: Suspended in UISP Only
- Note says: "From UISP (no local record)"
- Service shows but no suspension date
- Customer info fetched automatically
- Details page works

### Step 4: Verify Other Tabs Still Work
```
✅ All Suspensions    → Shows all (active + resolved)
✅ Active Suspensions → Shows currently suspended (FROM UISP)
✅ Resolved Suspensions → Shows reactivated services
✅ Candidates         → Shows eligible to suspend
```

---

## API Call Verification

### Check that UISP was called:

```bash
# View application logs
sudo journalctl -u fnb-web-gui.service -n 30
```

Look for message like:
```
Fetched X suspended services from UISP
```

### Manual API Test:

```bash
# Test the UISP endpoint directly
curl -H "X-Auth-App-Key: YOUR_API_KEY" \
  "https://uisp-ros1.afrieta.com/crm/api/v1.0/clients/services?statuses[]=3"
```

---

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Page shows "No suspensions found" | Check UISP - maybe nothing is suspended |
| Page won't load | Check logs: `journalctl -u fnb-web-gui.service` |
| Services show but no customer | Click again - customer will be fetched & cached |
| Button click doesn't work | Refresh page (F5) and try again |

---

## What Changed (Technical)

**New UISP API Call:**
```
GET v1.0/clients/services?statuses[]=3
```

**New Method:** `fetch_suspended_services()` in UISP handler

**New Route Logic:** Active filter now calls UISP instead of database

**Benefits:**
- Shows real suspended services
- Always in sync with UISP
- Includes externally suspended services

---

## Files Changed

1. `app/uisp_suspension_handler.py` - Added API method
2. `app/suspension_routes.py` - Enhanced route logic
3. `app/templates/suspensions/list.html` - Better display

---

## Quick Commands

**Restart app:**
```bash
sudo systemctl restart fnb-web-gui.service
```

**Check status:**
```bash
systemctl status fnb-web-gui.service
```

**View logs:**
```bash
sudo journalctl -u fnb-web-gui.service -n 50 -f
```

**Test URL:**
```
http://localhost:8901/suspensions/?filter=active
```

---

## Expected Behavior

| Tab | Shows |
|-----|-------|
| All Suspensions | Every suspension record ever created |
| **Active Suspensions** | **All services suspended in UISP (status=3)** ⭐ |
| Resolved Suspensions | Services that were suspended, now reactivated |
| Candidates | Customers eligible for suspension |

---

## Success Criteria

✅ Page loads without errors
✅ Shows suspended services from UISP
✅ Service names display correctly
✅ Customer information appears
✅ Status shows "UISP: SUSPENDED"
✅ Click on customer name works
✅ Pagination works (if >50 services)

---

**Done! The fix is live and ready to test.**
