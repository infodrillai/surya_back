# clssurya (Frappe backend)

Standalone Frappe app (no ERPNext) for the CL Surya ERP: masters, purchase, 3-stage production batches,
quotation (versioned), sales order (admin approval), dispatch, weighted-average stock ledger.
Targets Frappe v15, site `clssurya.local`.

## Install

```bash
bench init --frappe-branch version-15 frappe-bench && cd frappe-bench
bench get-app /path/to/backend              # this folder (contains pyproject.toml)
bench new-site clssurya.local --admin-password admin
bench use clssurya.local
bench --site clssurya.local execute clssurya.install.check_name_collisions   # task-1 name check (expect: none)
bench --site clssurya.local install-app clssurya
bench --site clssurya.local set-config developer_mode 1
bench --site clssurya.local set-config company_state "Gujarat"              # decides CGST+SGST vs IGST
bench start                                                                   # web :8000, socket :9000
```

Create users in `/app/user` and give them one of the roles **CS Admin**, **CS Store**, **CS Production**, **CS Sales**.

## Key rules in code
- `utils/stock_service.py` is the only writer of `Stock Ledger Entry` / `Inventory` (row locks, weighted average, negative-stock block, reversals).
- `utils/base.py`: Save never touches stock. `complete()` posts stock in one transaction; completed docs are locked in `validate` and `on_trash`; only `reopen()` (admin) reverses. Reopen is blocked while later movements depend on the document.
- `utils/costing.py`: all formulas, tested against the plan examples.
- `api.py`: `get_master_versions`, `get_masters`, `get_stage_rows`, `get_stock_by_stage`, `get_finished_cost`, `run_action`.
- Masters bump `Master Version` and publish `masters_changed` for the React cache.

## Tests
```bash
python -m unittest clssurya.tests.test_costing        # pure maths, no bench needed
```

## Regenerating DocTypes
Edit `tools/generate_doctypes.py`, run it, then `bench --site clssurya.local migrate`.
