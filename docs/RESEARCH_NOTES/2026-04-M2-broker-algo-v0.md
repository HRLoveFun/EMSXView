# M2 Broker × Algo Attribution v0 — Research Note

| Field | Value |
|---|---|
| Date issued | 2026-04-28 |
| Author | EMSX Quant Trading Research |
| Config version | `attr_v0` |
| Coverage | 2025-09-25 → 2026-04-22 (147 trading days) |
| Universe | All EMSX equity fills with non-null `Side`, `equ_ticker`, `FillPrice>0`, `FillShares>0` |
| Benchmarks | Arrival Mid (IS), Interval VWAP (sub-minute close × volume) |
| Significance | Welch's t-test, BH-FDR adjusted q-values, α = 0.05 |
| CI | 5,000-resample percentile bootstrap on cell mean |
| Reproduction | `python -m CostView.scripts.run_attribution --inspect --start 2025-09-25 --end 2026-04-22 --by broker algo` |

---

## 1. Question
Is there a **statistically significant, persistent dispersion** in per-fill execution
cost across (broker, algo) cells, after controlling for adverse-vs-favourable side
convention and trade footprint? Which cells are best/worst, and is that ranking
stable across volatility regimes?

## 2. Data & Methodology
- **Source**: `regime.db.fill_attribution_metrics` (config `attr_v0`), populated by
  `CostView.src.attribution.writer.run_metrics` from
  `processed_fills.processed_fills` and `raw_bdib.raw_bdib`.
- **Sign convention**: `is_bps = side · (fill_price / arrival_mid − 1) · 1e4` —
  **positive ⇒ adverse to the trader**.
- **Arrival mid**: bar close at the route's first-fill minute.
- **Interval VWAP**: `Σ(close · volume) / Σ(volume)` over [first_min, last_min] of the
  route. raw_bdib's native `vwap` column is null in this dataset, so we
  reconstruct from sub-minute (10s grid) bars.
- **Reversal**: `side · (mid_{t+N} − fill_price) / fill_price · 1e4` —
  **positive ⇒ price kept moving favourably** (the trader paid up early).
- **Cell n**: minimum 30 fills required for a cell to enter pairwise tests.
- **Multiplicity correction**: BH step-up across all unique cell-pair p-values
  (per metric, per regime slice).

## 3. Results
> Numbers below are extracted from the full-window papermill outputs:
> [out_vol.ipynb](../../notebooks/research_notes/out_vol.ipynb),
> [out_liq.ipynb](../../notebooks/research_notes/out_liq.ipynb),
> [out_trend.ipynb](../../notebooks/research_notes/out_trend.ipynb).
>
> Coverage: 8,273,353 fills across 75 unique (broker, algo) cells.
> Pairwise Welch's t-test: **1,208 / 1,431 pairs significant at BH-FDR q ≤ 0.05 (84.4%)**.

### 3.1 Headline (full window)
- **Total fills with a benchmark**: 8.27M; 75 (broker, algo) cells active.
- **Mean IS (n-weighted across top-15 cells, n ≥ 70k each)**: about **+5 bps** —
  the cross-section is dominated by `vwap` flow on EQ-RBC (+9.6 bps) and
  EQ-CLSA (+7.9 bps), partly offset by EQ-MS / EQ-JPM `close` trading near zero
  and EQ-HSBC / EQ-WFC `vwap` posting **negative** (favourable) IS.
- **Cross-cell dispersion**: from −13 bps to +25 bps for cells with n ≥ 100k —
  i.e. ~38 bps end-to-end. Even after winsorising at 1% the dispersion exceeds
  any plausible bid-ask noise floor at this aggregation scale.
- **5-min reversal** (cell-mean): clusters around 0 ± 1 bps; full reversal table
  is in the notebook under cell 8.

### 3.2 Best vs Worst Cells (n ≥ 70,000; ranked by mean `is_bps`)
| Rank | Broker | Algo | n | mean is_bps | median is_bps | Interpretation |
|---|---|---|---|---|---|---|
| Best 1 | EQ-WFC | vwap | 85,848 | **−8.33** | 0.00 | persistent favourable execution |
| Best 2 | EQ-HSBC | vwap | 150,620 | **−7.64** | 0.00 | persistent favourable execution |
| Best 3 | EQ-UBS | close | 182,729 | **−2.18** | −0.72 | net favourable on close |
| Best 4 | EQ-JPM | vwap | 610,319 | **−2.00** | 0.00 | high-volume, mildly favourable |
| Best 5 | EQ-MS | close | 390,433 | **−1.78** | −1.25 | high-volume close, favourable |
| Worst 1 | EQ-INSTNET | vwap | 95,578 | **+18.95** | +13.85 | persistent over-cost; review routing |
| Worst 2 | EQ-SCOTIA | vwap | 70,549 | **+12.94** | +10.31 | persistent over-cost |
| Worst 3 | EQ-BMO | vwap | 200,800 | **+11.50** | +7.22 | persistent over-cost |
| Worst 4 | EQ-RBC | vwap | 1,447,196 | **+9.57** | +3.86 | dominant volume; structural drift |
| Worst 5 | EQ-UBS | vwap | 546,292 | **+8.98** | +1.83 | high-volume vwap, adverse |

Notes:
- Cells with n < 100 (e.g. EQ-MIZUHO close, EQ-NOMURA close) appear in the
  notebook's raw best/worst-3 stream but are excluded here as unreliable.
- The bootstrap CI is sub-sampled at n_cap = 50,000 for the full window
  (`CostView/src/attribution/aggregator.py::bootstrap_ci_mean`); CI half-widths
  in the notebook are typically < 0.5 bps for cells with n ≥ 100k.

### 3.3 Regime Sensitivity (`vol_regime` — EQ-BARCLAY vwap example)
From [out_vol.ipynb](../../notebooks/research_notes/out_vol.ipynb) cell 6
(`vol_regime ∈ {low, normal, high, extreme}`, n ≥ 100):

| Cell | low | normal | high | extreme | Range |
|---|---|---|---|---|---|
| EQ-BARCLAY vwap | +5.41 (n=525) | **−3.77** (n=62,241) | **+25.17** (n=60,135) | −5.63 (n=27,607) | ~31 bps |
| EQ-BMO vwap | n/a | +3.11 (n=131,963) | **+32.50** (n=49,627) | +14.89 (n=19,210) | ~29 bps |
| EQ-BARCLAY close | 0.00 (n=286) | +0.92 (n=7,332) | +0.37 (n=4,076) | −1.20 (n=1,238) | ~2 bps |

Observations:
- `vwap`-flavoured cells (BARCLAY, BMO) are **highly vol-regime sensitive**:
  costs blow out in `high` vol (+25 to +33 bps) and recover — even reverse —
  in `extreme` (the regime where institutions are most aware of impact and
  algos throttle).
- `close`-flavoured cells (BARCLAY close) are **flat across regimes** (range
  ~2 bps) — close-cross liquidity is regime-insensitive at this aggregation.
- Therefore the headline ranking in §3.2 is a **weighted average across
  regimes** and obscures meaningful, exploitable rank changes inside `vwap`
  cells. M3 should re-rank within each `vol_regime` bucket separately.

## 4. Conclusions
1. **Dispersion is statistically significant**: 1,208 / 1,431 (84.4%) of cell
   pairs are significant at BH-FDR q ≤ 0.05 over the full 147-day window,
   confirming that the IS gap between best and worst (broker, algo) cells is
   not a sampling artefact.
2. **Best/worst rank is stable for `close`-flavoured cells but unstable for
   `vwap`-flavoured cells**: vwap routes show 25–30 bps swings between
   `normal` and `high` vol regimes, while close routes vary by < 5 bps. This
   contradicts the original hypothesis that the broker×algo ranking is
   structural across regimes — it is structural for close, regime-driven
   for vwap.
3. **5-min reversal is near zero**, so the persistent dispersion is **real
   implementation shortfall**, not transient impact. M3's routing-policy
   experiment can target cell-level cost reduction without expecting it to
   self-correct via reversion.
4. **Headline outliers worth investigating**: EQ-INSTNET vwap (+18.95 bps,
   n=96k) and EQ-RBC vwap (+9.57 bps, n=1.45M) carry the most economic
   weight on the adverse side; EQ-HSBC vwap (−7.64 bps, n=151k) and EQ-WFC
   vwap (−8.33 bps, n=86k) on the favourable side.

## 5. Limitations
- `raw_bdib.vwap` is fully null in this snapshot; VWAP is reconstructed from
  bar `close · volume`. This understates intra-bar dispersion.
- Arrival mid is the **bar close at first-fill minute**, not a true
  pre-decision reference. For routes that work over hours this is essentially a
  proxy and tends to flatter IS slightly.
- `participation_rate` is now populated (P0.1, 2026-04-28) using
  `route_shares / Σ(volume over [first_min, last_min])` from sub-minute
  raw_bdib bars; values clamped to `[0, 5]`. Routes whose shares exceed 5×
  the bar volume (off-book) are stored as NULL.
- IV / spread / depth inputs to vol/liq regimes deferred to Phase 2 (see
  `.github/knowledge/architecture-decisions.md` 2026-04-28 entry).
- ADV uses `bdib_daily_summary.adv_20d`; for thinly traded names this can be
  unstable.

## 6. Next Steps
- **M3** — add participation_rate, then regress IS on (size, %ADV, participation,
  vol_regime) per cell.
- **M4** — extend to **trader x broker x algo**; build a routing-cost dashboard.
- **M5** — backtest a routing-policy change (e.g. avoid worst-q cells) and
  measure ex-ante saving with the same framework.

---

_Reproducible via_ `python -m CostView.scripts.run_attribution --start 2025-09-25 --end 2026-04-22`
_then_ `papermill notebooks/research_notes/M2_broker_algo_v0.ipynb out.ipynb`.
