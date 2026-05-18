# Migration Verification Baseline

> Generated: 2026-05-14 | Branch: refactor/architecture

## Build Output (Pre-Migration)

| Chunk | Size | Gzip |
|-------|------|------|
| index.html | 1.00 kB | 0.40 kB |
| index.css | 109.68 kB | 18.26 kB |
| vendor-icons | 13.99 kB | 5.09 kB |
| vendor-ui | 26.13 kB | 8.46 kB |
| module-marketview | 27.40 kB | 6.49 kB |
| module-databaseview | 28.86 kB | 7.90 kB |
| module-costview | 88.56 kB | 21.83 kB |
| vendor-radix | 106.40 kB | 29.88 kB |
| vendor-react | 189.09 kB | 59.14 kB |
| vendor-misc | 190.51 kB | 65.49 kB |
| vendor-charts | 264.76 kB | 60.50 kB |
| index (main app) | 284.52 kB | 71.72 kB |

**Total chunks**: 12 (excl. CSS/HTML)
**Build time**: 5.77s

## TypeScript Compilation

`tsc --noEmit`: PASS (zero errors)

## Smoke Test Checklist

These manual checks must pass after each migration step:

- [ ] Dev server starts (`npm run dev`)
- [ ] WebSocket connects (green indicator in toolbar)
- [ ] Order table loads with data
- [ ] Route table loads with data
- [ ] Tab switching works (Monitor / Trade / Route Engine / Settings)
- [ ] Module tab switching works (Execution / CostView / MarketView / Database)
- [ ] Settings save persists (broker algorithms, market-broker mapping)
- [ ] Monitor conditions filter works
- [ ] Batch route order dialog opens
- [ ] Toast notifications appear on actions

## Test Baseline

No automated frontend tests exist currently. Verification relies on:
1. `tsc --noEmit` (type safety)
2. `vite build` (bundle integrity)
3. Manual smoke tests above
4. Backend `pytest` (separate)
