"""
Regime & attribution analysis stages (S8–S10).

S8  RegimeDailyFeaturesStage — vol/liq/trend classification
S9  RegimeFillTaggerStage    — regime label fill tagging
S10 AttributionMetricsStage  — IS/VWAP/reversal metrics
"""

from __future__ import annotations

import logging

from .base import BaseStage, _to_iso_safe
from .context import PipelineContext

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# S8: RegimeDailyFeaturesStage
# ═══════════════════════════════════════════════════════════════
class RegimeDailyFeaturesStage(BaseStage):
    """Stage 8: build daily regime features (market_index → vol/liq/trend) for target_dates."""
    @property
    def name(self) -> str: return "8. Regime Daily Features (vol/liq/trend)"

    def process(self, context: PipelineContext) -> bool:
        if not context.target_dates:
            logger.info("Stage 8: no target_dates; skipping")
            context.summary["regime_daily"] = {"skipped": True}
            return True
        try:
            from CostView.src.regime import liquidity_regime, market_index_loader, trend_regime, vol_regime
            from CostView.src.regime.config import ensure_default_config
            from CostView.src.regime.run_journal import run_journal
        except ImportError as e:
            logger.warning(f"Skipping regime daily stage: {e}")
            context.summary["regime_daily"] = {"skipped": True, "error": str(e)}
            return True

        opts = context.config.get("regime", {}) or {}
        skip_fetch = bool(opts.get("skip_fetch", False))
        version = opts.get("config_version") or ensure_default_config()

        iso_dates = [_to_iso_safe(d) for d in context.target_dates]
        iso_dates = [d for d in iso_dates if d]
        if not iso_dates:
            return True
        start, end = min(iso_dates), max(iso_dates)

        results = {}
        if not skip_fetch:
            with run_journal("market_index_loader", config_version=version, start=start, end=end) as rec:
                n = market_index_loader.load_market_index(start, end)
                rec.set_rows(n)
                results["market_index_loader"] = n
        for stage_name, fn in (
            ("vol_regime", vol_regime.classify),
            ("liquidity_regime", liquidity_regime.classify),
            ("trend_regime", trend_regime.classify),
        ):
            with run_journal(stage_name, config_version=version, start=start, end=end) as rec:
                n = fn(start, end, config_version=version)
                rec.set_rows(n)
                results[stage_name] = n

        context.summary["regime_daily"] = {"config_version": version, **results}
        return True


# ═══════════════════════════════════════════════════════════════
# S9: RegimeFillTaggerStage
# ═══════════════════════════════════════════════════════════════
class RegimeFillTaggerStage(BaseStage):
    """Stage 9: tag fills with regime labels (depends on Stage 8)."""
    @property
    def name(self) -> str: return "9. Regime Fill Tagger"

    def process(self, context: PipelineContext) -> bool:
        if not context.target_dates:
            logger.info("Stage 9: no target_dates; skipping")
            return True
        try:
            from CostView.src.regime import fill_regime_tagger
            from CostView.src.regime.config import ensure_default_config
            from CostView.src.regime.run_journal import run_journal
        except ImportError as e:
            logger.warning(f"Skipping regime tagger stage: {e}")
            context.summary["regime_tagger"] = {"skipped": True, "error": str(e)}
            return True

        opts = context.config.get("regime", {}) or {}
        version = opts.get("config_version") or ensure_default_config()

        iso_dates = [_to_iso_safe(d) for d in context.target_dates]
        iso_dates = [d for d in iso_dates if d]
        if not iso_dates:
            return True
        start, end = min(iso_dates), max(iso_dates)

        with run_journal("fill_regime_tagger", config_version=version, start=start, end=end) as rec:
            s = fill_regime_tagger.tag_fills(start, end, config_version=version)
            rec.set_rows(s["rows_upserted"])
        context.summary["regime_tagger"] = s
        return True


# ═══════════════════════════════════════════════════════════════
# S10: AttributionMetricsStage
# ═══════════════════════════════════════════════════════════════
class AttributionMetricsStage(BaseStage):
    """Stage 10: per-fill attribution metrics (IS/VWAP/reversal). Depends on Stage 9."""
    @property
    def name(self) -> str: return "10. Attribution Metrics"

    def process(self, context: PipelineContext) -> bool:
        if not context.target_dates:
            logger.info("Stage 10: no target_dates; skipping")
            return True
        try:
            from CostView.src.attribution.writer import run_metrics
            from CostView.src.attribution.repositories import (
                SqliteFillRepository, SqliteBarDataRepository,
                SqliteRegimeRepository, SqliteAttributionConfigRepository,
            )
        except ImportError as e:
            logger.warning(f"Skipping attribution metrics stage: {e}")
            context.summary["attribution_metrics"] = {"skipped": True, "error": str(e)}
            return True

        iso_dates = [_to_iso_safe(d) for d in context.target_dates]
        iso_dates = [d for d in iso_dates if d]
        if not iso_dates:
            return True
        start, end = min(iso_dates), max(iso_dates)
        with context.db.regime_write._ensure_schema_context():
            n = run_metrics(start, end, config_version=None, fill_repo=SqliteFillRepository(context.connection_manager),
                            bar_repo=SqliteBarDataRepository(context.connection_manager),
                            regime_repo=SqliteRegimeRepository(context.connection_manager),
                            config_repo=SqliteAttributionConfigRepository(context.connection_manager))
        context.summary["attribution_metrics"] = {"rows_upserted": n}
        return True
