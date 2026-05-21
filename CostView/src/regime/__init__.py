"""
Regime classification stubs — redirected to DataPipeline.

Core implementation moved to DataPipeline/analysis/regime/.
This package re-exports for backward compatibility with existing scripts.
"""
from DataPipeline.analysis.regime import *

# Explicit re-exports for common direct imports
from DataPipeline.analysis.regime import fill_regime_tagger
from DataPipeline.analysis.regime import liquidity_regime
from DataPipeline.analysis.regime import market_index_loader
from DataPipeline.analysis.regime import trend_regime
from DataPipeline.analysis.regime import vol_regime
