# Archived Customer Filter - Active Suspensions

**Date:** 2025-12-14 03:39 UTC
**Status:** ✅ Implemented & Tested
**File:** ARCHIVED_CUSTOMER_FILTER.md

---

## What Changed

Added filtering to exclude suspended services from **archived customers** (isArchived=true).

The "Active Suspensions" tab now shows ONLY suspended services where:
- ✅ Service status = 3 (suspended in UISP)
- ✅ Customer isArchived = false (not archived)

---

## Implementation

### 1. Added Database Column
**File:** `app/models.py`

Added new field to Customer model:
```python
is_archived = db.Column(db.Boolean, default=False, index=True)
```

**Migration:** Column added to customers table with default value of 0 (false)

### 2. Updated UISP Handler
**File:** `app/uisp_suspension_handler.py` (line 87)

Now fetches archived status from UISP client data:
```python
customer.is_archived = client_data.get('isArchived', False)
```

### 3. Added Filter Logic
**File:** `app/suspension_routes.py` (lines 97-100)

Skips archived customers when building suspension list:
```python
# Skip archived customers
if customer.is_archived:
    logger.info(f"Skipping archived customer {client_id} for service {service_id}")
    continue
```

---

## Current Status

### Suspended Services Analysis
```
Total from UISP: 17 services (status=3)
Active Customers: 17 services will display ✓
Archived Customers: 0 services filtered out ✓
```

### Services Displayed
1. Service 1673 - Ayola Geca (CID: 757)
2. Service 1733 - Akbar Faruk Bhula (CID: 112)
3. Service 1844 - Elrise Botha (CID: 700)
4. Service 1947 - Afikile Fubu (CID: 878)
5. Service 1979 - Leshego Malema (CID: 888)
6. Service 2015 - Akil Kazi (CID: 449)
7. Service 2246 - Sibusiso Mazibuko (CID: 981)
8. Service 2309 - Khanyiswa Stampu (CID: 1008)
9. Service 2355 - Anotida Nicole Chido Potera (CID: 1028)
10. Service 2376 - Gugu Mdletshe (CID: 1047)
11. Service 2543 - Daleshney Scharnick (CID: 1139)
12. Service 2548 - Bongani Mbelu (CID: 1143)
13. Service 2556 - Ragel Josephine Kock (CID: 1148)
14. Service 2579 - William Nhlapo (CID: 1166)
15. Service 2600 - Anthea Scholtz (CID: 900)
16. Service 2601 - Linda Perseverance Ngwenya (CID: 1181)
17. Service 2659 - Kefilwe Victoria (CID: 1222)

All 17 are from **active (non-archived)** customers.

---

## Files Modified

| File | Changes |
|------|---------|
| `app/models.py` | Added `is_archived` column to Customer model |
| `app/uisp_suspension_handler.py` | Fetch `isArchived` from UISP client data |
| `app/suspension_routes.py` | Skip archived customers in filter logic |

---

## Database Changes

### Migration Executed
```sql
ALTER TABLE customers ADD COLUMN is_archived BOOLEAN DEFAULT 0
```

**Status:** ✅ Applied successfully

### Column Details
```
Table: customers
Column: is_archived
Type: BOOLEAN
Default: 0 (false)
Indexed: Yes
```

---

## How It Works

### Data Flow
```
1. Fetch suspended services from UISP (status=3)
   ↓
2. For each service:
   - Get customer data
   - Fetch `isArchived` field from UISP
   - Store in local database
   ↓
3. When displaying active suspensions:
   - Check if customer.is_archived == true
   - If YES: Skip service (log and continue)
   - If NO: Display service
   ↓
4. Result: Show only suspended services from active customers
```

### Example Logic
```python
if customer.is_archived:
    logger.info(f"Skipping archived customer {client_id}")
    continue  # Don't display this service
else:
    suspensions_data.append(suspension_object)  # Display
```

---

## Testing Verification

### Test Results
```
✓ Database migration successful
✓ is_archived column added
✓ 17 suspended services fetched from UISP
✓ All customers checked for archived status
✓ All 17 customers are ACTIVE (not archived)
✓ All 17 services will display
✓ Application running without errors
```

### Manual Verification
```bash
# View customer archived status
SELECT uisp_client_id, first_name, last_name, is_archived
FROM customers
WHERE uisp_client_id IN (757, 112, 700, 878, 888);
# Result: All show is_archived = 0 (false)
```

---

## What Happens With Archived Customers

### Current Behavior
If a service is suspended in UISP and belongs to an **archived** customer:
- Service is fetched from UISP (status=3)
- Customer data is fetched from UISP (isArchived=true)
- Service is **skipped** and NOT displayed
- Action is logged: "Skipping archived customer X for service Y"

### Rationale
Archived customers should not appear in active suspension management because:
- They are no longer active clients
- Suspending archived services may violate business rules
- Reduces clutter in active management view
- Improves focus on current active customers

---

## Data Dictionary

### Customer.is_archived
| Attribute | Value |
|-----------|-------|
| Field Name | is_archived |
| Data Type | BOOLEAN |
| Default | False (0) |
| Indexed | Yes |
| Source | UISP client data (isArchived field) |
| Usage | Filter out archived customers from active suspensions |

---

## Future Enhancement

If archived customers need to be managed separately:
1. Create a separate "Archived Suspensions" filter
2. Query: `is_archived=true AND suspension.is_active=true`
3. Display in separate view for archival/cleanup purposes
4. Add audit trail for why they were archived

---

## Logs & Monitoring

### Log Messages
When an archived customer service is encountered:
```
Skipping archived customer 123 for service 456
```

### How to Check
```bash
# View filtered services in logs
sudo journalctl -u fnb-web-gui.service | grep "archived"
```

---

## Verification Commands

### Check Database Column
```sql
SELECT COUNT(*) FROM customers WHERE is_archived = 1;
-- Currently returns: 0 (no archived customers in test data)
```

### Check Customer Data
```sql
SELECT uisp_client_id, first_name, is_archived
FROM customers
LIMIT 5;
```

### Check UISP Integration
```bash
# Test if UISP returns isArchived field
curl -H "X-Auth-App-Key: <API_KEY>" \
  "https://uisp-ros1.afrieta.com/crm/api/v2.1/clients/1"
# Look for "isArchived" in response
```

---

## Summary

✅ **Archived customer filter is active**

The "Active Suspensions" tab now correctly:
- Fetches all suspended services from UISP (status=3)
- Checks if each customer is archived (isArchived)
- Filters OUT services from archived customers
- Displays ONLY services from active customers
- Shows 17 suspended services from active customers

**Result:** Clean, focused view of active suspension management

---

**Deployment Date:** 2025-12-14 03:39 UTC
**Status:** ✅ Live & Tested
**Ready:** YES
