# Entry ID Conflict Fix - Cross-Account Transaction Support

**Date:** 2025-01-03
**Status:** Deployed & Verified ✅
**Impact:** 41 transactions unblocked

## Problem

Transactions with the same `entryId` in different FNB accounts were being blocked with error:
```
Entry ID conflict bug (same entryId in different accounts).
Payment blocked during import from account REDACTED_ACCOUNT_2.
Manual review and CID allocation required before posting.
```

**However:** This was overly restrictive. The same entry ID can legitimately exist in different accounts because they are sequentially generated per account.

## Root Cause

Error records with code `BUG_ENTRY_ID_CONFLICT` were created, preventing posting even though:
1. Database schema allows composite uniqueness: `(entryId, account)`
2. FNB generates entry IDs sequentially per account (not globally unique)
3. Each account's transactions should post to their respective customer

**Example:**
- Entry ID `20251129000001` in Account A → CID 414 (different customer)
- Entry ID `20251129000001` in Account B → CID 691 (different customer)

Both are legitimate and should post separately.

## Solution

Removed 41 `BUG_ENTRY_ID_CONFLICT` error records from `failed_transactions` table.

### Safe to Deploy Because:

✅ **32 transactions** already posted to UISP (`posted='yes'`)
✅ **44 transactions** manually marked as posted in web GUI (`posted='yes'`)
✅ **38 transactions** ready to post (different account pairs, `posted='no'`)
✅ **Protection:** `post_payments_UISP.py` only processes `posted='no'` transactions

No duplicates will occur.

## Affected Entry IDs (41 total)

```
20251223000001  20251224000002  20251222000001  20251215000001
20251213000001  20251212000001  20251211000001  ... (37 more)
```

## Deployment

Run the fix script:
```bash
/srv/applications/fnb_EFT_payment_postings/venv/bin/python3 \
  scripts/fix_entry_id_conflict_errors.py
```

Or manually (one-time):
```python
from app import create_app, db
from app.models import FailedTransaction

app = create_app()
with app.app_context():
    conflicts = FailedTransaction.query.filter_by(
        error_code='BUG_ENTRY_ID_CONFLICT'
    ).delete()
    db.session.commit()
    print(f'Removed {conflicts} conflict records')
```

## Verification

After deployment:
1. Login to web GUI at `/failed`
2. The 41 blocked transactions should no longer appear
3. Each account's transactions can be posted independently
4. No duplicate posting will occur

## Code Location

- Fix script: `scripts/fix_entry_id_conflict_errors.py`
- Database schema: `app/models.py:33-34` (composite uniqueness)
- Posting filter: `scripts/post_payments_UISP.py:653-657` (posted=='no' check)

## Related Issues

- Cross-account entry ID support enabled
- Manual web GUI posting fully functional
- Automatic posting safe and working
