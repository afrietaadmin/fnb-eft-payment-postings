# Quick Reference - Customer Data & Refresh Fixes

**Date:** 2025-12-14
**Status:** ✅ COMPLETE

---

## Issues Fixed

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Customers showing "good standing" | No services/invoices loaded from UISP | Auto-fetch data in customer details route |
| Services showing (0) | Only queried for active status (1), not suspended (3) | Fetch all services regardless of status |
| Invoices showing (0) | Wrong field names from UISP API | Fixed: `number`, `total`, `amountToPay` |
| Refresh button errors | log_user_activity() wrong parameters (8 vs 2) | Fixed: corrected all 4 logging calls |

---

## Files Changed

### app/suspension_routes.py
- **Line 231-240:** Add auto-fetch in customer_suspension_details()
- **Line 317-320:** Fix log_user_activity() in suspend service
- **Line 374-377:** Fix log_user_activity() in reactivate service
- **Line 467-470:** Fix log_user_activity() in bulk suspend
- **Line 515-517:** Fix log_user_activity() in refresh endpoint

### app/uisp_suspension_handler.py
- **Line 116-169:** fetch_and_cache_services() - get all statuses
- **Line 154-157:** Use correct field names (name, price)
- **Line 215-226:** Fix invoice field mappings (number, total, amountToPay)
- **Line 507-534:** Map numeric invoice status codes (1-6)

---

## UISP Field Mappings (Corrected)

### Services
- ❌ `serviceName` → ✅ `name`
- ❌ `billingAmount` → ✅ `price`

### Invoices
- ❌ `invoiceNumber` → ✅ `number`
- ❌ `totalAmount` → ✅ `total`
- ❌ `remainingAmount` → ✅ `amountToPay`
- ❌ String status → ✅ Numeric status (1-6)

---

## Test Results

**Customer 757 (Ayola Geca):**
```
✓ is_active: False
✓ is_archived: False
✓ Services: 1 (15Mbs Fibre Uncapped - suspended)
✓ Invoices: 10 (with correct amounts and status)
✓ Account outstanding: 407.2 ZAR
```

---

## Commands

```bash
# Verify application status
systemctl status fnb-web-gui.service

# View logs
sudo journalctl -u fnb-web-gui.service -n 50 -f

# Test refresh for customer 757
./venv/bin/python3 << 'EOF'
from app import create_app
from app.models import Customer
from app.uisp_suspension_handler import UISPSuspensionHandler

app = create_app()
with app.app_context():
    handler = UISPSuspensionHandler()
    customer = Customer.query.filter_by(uisp_client_id=757).first()

    # Auto-refresh
    customer = handler.fetch_and_cache_client(757)
    handler.fetch_and_cache_services(customer)
    handler.fetch_and_cache_invoices(customer)

    print(f"✓ Customer: {customer.first_name} {customer.last_name}")
    print(f"✓ Services: {len(customer.services)}")
    print(f"✓ Invoices: {len(customer.invoices)}")
EOF
```

---

## Deployment

- **Date:** 2025-12-14 04:07 UTC
- **Status:** ✅ LIVE
- **Ready:** YES

