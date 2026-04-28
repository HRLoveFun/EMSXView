# M2 Broker × Algo Attribution v0 — Research Note

| Field | Value |
|---|---|
| Date issued | _to be filled when run is reproduced_ |
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
> _Numbers below are placeholders; the notebook
> [M2_broker_algo_v0.ipynb](../../notebooks/research_notes/M2_broker_algo_v0.ipynb)
> regenerates Tables 1–2 and Figures 1–2._

### 3.1 Headline (full window)
- **Mean IS across all fills**: ~ +20 bps (adverse, in line with cross-section
  norms for execution shortfalls in mixed Asia/Americas universe).
- **Mean Interval-VWAP slippage**: ~ +5 bps (much closer to zero — algos hit their
  own benchmark much better than they hit arrival).
- **5-min reversal**: ~ −1 bps on average across cells, indicating that on average
  fills are **not over-paying transient impact** — the price does not reliably
  retrace after the trader prints.

### 3.2 Best vs Worst Cells (filtered to n ≥ 100, q ≤ 0.05)
| Rank | Broker | Algo | n | mean is_bps | 95% CI | Interpretation |
|---|---|---|---|---|---|---|
| Best 1 | _fill from notebook_ | | | | | tight, persistent under-cost |
| Best 2 |  | | | | | |
| Best 3 |  | | | | | |
| Worst 1 |  | | | | | persistent over-cost; review routing |
| Worst 2 |  | | | | | |
| Worst 3 |  | | | | | |

### 3.3 Regime Sensitivity (`vol_regime`)
The same broker/algo cells are re-aggregated under `vol_regime ∈ {LOW, MID,
HIGH}`. We expect spreads to widen in HIGH vol; therefore IS should worsen
broadly and we look for cells whose **rank** changes (not absolute level).

| Cell | LOW mean | MID mean | HIGH mean | Stability |
|---|---|---|---|---|
| _fill from notebook_ | | | | |

## 4. Conclusions (auto-bullet template)
1. The dispersion in IS across (broker, algo) cells is **statistically
   significant** at BH-FDR ≤ 0.05 for the majority of pairs (see notebook §5).
2. The best and worst cells **persist across volatility regimes**, which
   suggests the dispersion is structural (routing / venue / algo behaviour)
   rather than a vol-regime artifact.
3. Average **5-min reversal is approximately zero**, so the cost dispersion is
   **not** mostly transient impact; it is closer to real implementation
   shortfall.

## 5. Limitations
- `raw_bdib.vwap` is fully null in this snapshot; VWAP is reconstructed from
  bar `close · volume`. This understates intra-bar dispersion.
- Arrival mid is the **bar close at first-fill minute**, not a true
  pre-decision reference. For routes that work over hours this is essentially a
  proxy and tends to flatter IS slightly.
- `participation_rate` is currently `NULL` in `fill_attribution_metrics`
  (TODO Stage 12 — needs interval volume per route).
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
