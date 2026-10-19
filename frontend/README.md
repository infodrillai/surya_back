# CL Surya web (React + JavaScript)

Vite, React 18, MUI, TanStack Query, React Hook Form + Zod, Zustand, Dexie (IndexedDB), JSDoc.

```bash
npm install
npm run dev        # http://localhost:5173 - proxies /api and /socket.io to the bench (127.0.0.1:8000 / :9000)
npm test           # formula tests (plan section 2 examples)
npm run build      # writes into ../backend/clssurya/public/erp  ->  /assets/clssurya/erp/index.html
```

Sidebar: UOM, Product, Category, Process, Purchase, Batch (Stage 1/2/3), Quotation, Sales Order, plus Vendor, Customer, Charge, BOM, Inventory, Dispatch.
Every list has Add, Edit and Delete. Transactions also have Complete / Reopen (admin), Quotation Revise / Create order, Sales Order Approve.

Masters live in IndexedDB (version-checked at startup, on focus, on socket reconnect, and invalidated live on `masters_changed`).
Rates, ledger and transactions are never cached locally. The server is authoritative for costing; `src/lib/formulas.js` only drives live previews.

Each screen is a config in `src/config/resources.jsx`; add a field there to add it to the list, form and validation.
