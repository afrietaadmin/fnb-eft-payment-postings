# Duplicate Check System Updates

## Date: 2025-12-13

## Changes Implemented

### 1. Marked 22 UISP Duplicates for Manual Review

**Script**: `scripts/mark_uisp_duplicates.py`

Marked all 22 transactions (including CID252) that were found to already exist in UISP:
- Added to `FailedTransaction` table with error code `DUPLICATE_UISP_MANUAL_REVIEW`
- Updated transaction status to `duplicate_manual_review`
- Created audit log entries

**Transactions Marked**:
- 21 transactions from 2025-11-28 (already in UISP from Nov 28-29)
- 1 transaction from 2025-12-12 (CID252)

**Total Amount**: R12,966.00

---

### 2. Updated Duplicate Detection Logic

**File**: `scripts/post_payments_UISP.py`

**Function**: `check_duplicate_payment(txn)`

#### Old Behavior:
- Only checked local database
- Looked for `posted='yes'` transactions
- Used configurable `DUPLICATE_DETECTION_DAYS` (default 7 days)
- Missed payments posted directly to UISP

#### New Behavior:
- **Always queries UISP API** for existing payments
- Checks last **15 days** (hardcoded)
- Matches on **same CID + same amount**
- Returns detailed duplicate info from UISP

#### Detection Criteria:
```python
UISP_DUPLICATE_DAYS = 15  # Fixed at 15 days
Match = Same CID AND Same Amount within 15 days
```

---

### 3. Manual Review Workflow

When a duplicate is detected in UISP:

1. **Transaction is NOT auto-skipped**
2. **Added to FailedTransaction table**:
   - Error Code: `DUPLICATE_UISP_MANUAL_REVIEW`
   - Reason: Includes UISP payment details (date, provider, method)
   - Resolved: `false`

3. **Transaction status updated** to `duplicate_manual_review`

4. **Logged** in audit trail

5. **Available in GUI** for manual intervention

---

### 4. Duplicate Information Returned

The function now returns a dict with:
```python
{
    'source': 'UISP',
    'amount': payment_amount,
    'created_date': created_date,
    'days_ago': days_ago,
    'provider': 'FNB-EFT',
    'provider_id': '...',
    'method': 'Unknown',
    'uisp_payment_id': '...'
}
```

---

## Testing

### Test Script: `scripts/check_uisp_duplicates.py`

Use this script to check for UISP duplicates before posting:
```bash
/srv/applications/fnb_EFT_payment_postings/venv/bin/python scripts/check_uisp_duplicates.py
```

This script:
- Queries UISP for each transaction
- Checks for same amount within 18 days
- Reports duplicates without making any changes

---

## Database Schema

### FailedTransaction Table
```sql
- entryId: Transaction entry ID
- reason: Detailed explanation including UISP payment info
- error_code: 'DUPLICATE_UISP_MANUAL_REVIEW'
- resolved: false (for manual review)
```

### Transaction Table
```sql
- status: Updated to 'duplicate_manual_review'
```

---

## Workflow Summary

```
Transaction Ready to Post
         ↓
Check UISP for duplicates (15 days, same CID + amount)
         ↓
    Duplicate Found?
         ↓
    Yes → Flag for Manual Review
          - Add to FailedTransaction
          - Status: 'duplicate_manual_review'
          - Error Code: 'DUPLICATE_UISP_MANUAL_REVIEW'
          - Available in GUI
         ↓
    No → Continue with posting
```

---

## Benefits

1. ✅ **Prevents double-posting** by checking UISP directly
2. ✅ **Catches payments posted outside the system**
3. ✅ **Configurable 15-day window** for duplicate detection
4. ✅ **Manual review workflow** instead of auto-skip
5. ✅ **Detailed duplicate information** for decision-making
6. ✅ **Audit trail** of all duplicate detections

---

## Important Notes

- Duplicate check happens **before** posting to UISP
- Uses UISP v1.0 API for payment queries
- 15-day window is **hardcoded** (not configurable)
- Requires UISP API credentials in config
- GUI must handle `DUPLICATE_UISP_MANUAL_REVIEW` error code
- Manual review allows legitimate double payments if needed

---

## Files Modified

1. `scripts/post_payments_UISP.py` - Updated duplicate check logic
2. Database - 22 transactions marked for manual review

## Files Created

1. `scripts/mark_uisp_duplicates.py` - Mark duplicates script
2. `scripts/check_uisp_duplicates.py` - Test script for UISP duplicates
3. `DUPLICATE_CHECK_UPDATES.md` - This documentation
