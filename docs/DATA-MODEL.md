# TechZone POS & ERP — Data Model (52 Tables & 63 Permissions)

## Overview

All TechZone data is stored in a single SQLite database at `data/shop.db` running in `WAL` mode (`synchronous=NORMAL`, `foreign_keys=ON`). The schema comprises **52 tables** managed by `app/db.py`, which handles creation, seeding, and non-destructive auto-migration on every startup.

---

## Mandatory Modular Plug-and-Play Data Isolation Rule

Every module's tables are designed for **Zero-Overhead Plug-and-Play Isolation**:
1. Core POS/Inventory tables store historical cost snapshots (`sale_items.cost_unit`, `repair_parts.cost_unit`) directly at transaction time so profit reports remain 100% accurate even if `purchases` or `accounting` is disabled.
2. When `purchases` or `accounting` is disabled via `owner.html`, no writes or queries are executed against their tables (`erp_hooks.is_module_active` returns `False` in `O(1)` time).
3. In `accounting`, sales/returns/installments/repairs create **two separate journal entries** in `journal_entries`:
   - The **Financial Invoice Entry** (`source_table='sales'`, etc.), whose `total_debit` and `total_credit` match the exact invoice `total`.
   - The **Perpetual Inventory Cost Entry** (`source_table='sales_cogs'`, etc.), which records `COGS` vs. `Inventory` separately.

---

## Core & Operational Tables (Tables 1–32)

1. `users` — System accounts, PBKDF2 PIN hashes, JSON permissions cache, `is_active`, `job_preset`, desktop preferences.
2. `categories` — Product categories (with `demo_profile` tag).
3. `products` — Product catalog (`sku`, `name`, `price`, `cost`, `qty`, `min_qty`, `tracked`, `expiry_date`, `demo_profile`).
4. `serials` — Individual serial/IMEI units (`in_stock`, `sold`, `in_repair`, plus `purchase_item_id` link).
5. `shifts` — Cash register shifts (`opening_cash`, `counted_cash`, `expected_cash`, `diff`).
6. `customers` — Customer CRM records with cached `total_purchases`, `credit_total`, `paid_total`, and `debt`.
7. `customer_ledger` — Unified chronological customer receivable ledger (`credit_sale`, `voucher`, `return_credit`, `adjustment`, `installment_charge`, `installment_payment`).
8. `sales` — POS and B2B sales headers (`invoice_no`, `subtotal`, `discount`, `tax`, `total`, `status`).
9. `sale_items` — Line items within a sale, including `cost_unit` snapshot at the moment of sale.
10. `payments` — Split payment lines (`cash`, `wallet`, `credit`, `ref_no`).
11. `customer_payments` — Customer collection vouchers (`RCV-...`).
12. `sale_returns` & 13. `sale_return_items` — Customer return headers and line items.
14. `quotations` & 15. `quotation_items` — B2B price quotations and A4 invoices.
16. `used_device_purchases` — Second-hand device buying records (`USD-...`).
17. `repairs` & 18. `repair_parts` — Maintenance tickets (`RPR-...`) and consumed spare parts (with `cost_unit`).
19. `stock_movements` — Full inventory movement audit trail.
20. `settings` — System-wide key-value settings.
21. `installment_plans`, 22. `installment_items`, 23. `installment_payments` — Scheduled installment financing contracts (`INS-...`) and receipts (`INP-...`).
24. `owner_auth`, 25. `owner_audit_log`, 26. `modules` (15 built-in modules), 27. `ui_labels`, 28. `business_profiles` (5 profiles) — Owner Control & Module Registry tables.
29. `user_permissions`, 30. `permission_roles` (7 job presets), 31. `perm_audit_log` — Granular RBAC tables.
32. `product_cost_history` — Historical log of every Weighted Average Cost (`WAC`) transition (`old_qty`, `old_cost`, `added_qty`, `unit_cost`, `landed_unit_cost`, `new_qty`, `new_wac`).

---

## Purchases & Suppliers Module Tables (`purchases` — Tables 33–41)

33. `suppliers` — Supplier directory (`code`, `name`, `company_name`, `phone`, `tax_reg_no`, `tax_card_no`, `payment_terms_days`, `credit_limit`, `opening_balance`, `total_purchases`, `paid_total`, `balance`).
34. `purchase_orders` & 35. `purchase_order_items` — Purchase orders (`PO-...`) and ordered items before receipt.
36. `purchases` & 37. `purchase_items` — Posted/draft supplier purchase bills (`PUR-...`) with `shipping_cost`, `tax` (14% VAT input), `wht_amount` (1%/3% withholding tax), `landed_unit_cost`, `expiry_date`, and `serials_json`.
38. `purchase_returns` & 39. `purchase_return_items` — Purchase return notes (`PRET-...`) reversing stock, WAC, and supplier balance.
40. `supplier_payments` — Supplier payment vouchers (`SPY-...`) paid from main safe, bank, e-wallet, or active POS drawer.
41. `supplier_ledger` — Chronological Accounts Payable (`AP`) ledger per supplier (`opening`, `purchase_bill`, `payment`, `purchase_return`, `adjustment`).

---

## Double-Entry Accounting Module Tables (`accounting` — Tables 42–52)

42. `accounts` — Hierarchical Chart of Accounts (`code`, `name`, `parent_id`, `level`, `type`, `normal_balance`, `is_group`, `is_system`, `system_role`, `debit_total`, `credit_total`, `balance`, `active`). Seeded with **38 standard Arabic accounts**. Supports full CRUD (`account_save`, `account_delete` when zero movements/children and non-system) and Drag-and-Drop reparenting (`account_move`).
43. `fiscal_years` & 44. `fiscal_periods` — Financial years and monthly periods (`open` / `closed`) with year-end closing to Retained Earnings (`3103`).
45. `journal_entries` — Immutable double-entry journal headers (`entry_no` `JE-YYYY-NNNNN`, `entry_date`, `kind` IN `auto`/`manual`/`opening`/`reversal`/`closing`, `source_module`, `source_table`, `source_id`, `ref`, `memo`, `total_debit`, `total_credit`, `status` IN `posted`/`reversed`).
46. `journal_lines` — Balanced debit/credit lines (`entry_id`, `line_no`, `account_id`, `debit`, `credit`, `cost_center_id`, `party_type`, `party_id`, `memo`).
47. `treasury_accounts` — Financial safes, POS cash drawer, e-wallets, and bank accounts linked 1-to-1 with leaf asset accounts in `accounts`.
48. `treasury_transfers` — Internal liquidity transfers (`TRF-...`) between treasuries/banks.
49. `cost_centers` — Analytical cost centers (Main Showroom, Maintenance Workshop, B2B/Online).
50. `expense_categories` — Operational expense categories mapped to `52xx` expense accounts.
51. `expenses` — Operational expense vouchers (`EXP-...`) auto-posting journal entries.
52. `accounting_posting_rules` — Configurable mapping of 22 operational event roles (`cash_main`, `sales_revenue`, `cogs_sales`, `inventory_merchandise`, `vat_output`, `vat_input`, `wht_payable`, etc.) to `accounts.id`.

---

## Access Control Matrix (63 Granular Permissions in 12 Groups)

Defined in `app/permissions.py`:
- **Groups 1–10 (49 keys):** `pos` (9), `history` (6), `quotes` (4), `customers` (6), `installments` (4), `inventory` (5), `repair` (4), `buy_used` (2), `reports` (4), `admin` (5).
- **Group 11 — Purchases & Suppliers (`purchases`, 6 keys):** `purchases_view`, `purchases_create_edit`, `purchases_return`, `suppliers_view`, `suppliers_manage`, `purchases_payment`.
- **Group 12 — Accounting & Finance (`accounting`, 8 keys):** `accounting_coa_view`, `accounting_journal_view`, `accounting_journal_manual`, `accounting_statements_view`, `treasury_view`, `treasury_transfer`, `expenses_view`, `expenses_manage`.
