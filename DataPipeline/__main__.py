"""
DataPipeline CLI entry point.

Usage:
    python -m DataPipeline --once          # Run full pipeline once

Replaces CostView/scripts/daily_update.py as the canonical pipeline
execution entry point for backend subprocess invocation.
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

# P2-D5: Ensure EMSX root is on sys.path for standalone CLI invocation
# (python -m DataPipeline). This is a necessary bootstrapping step because
# DataPipeline is not yet a pip-installable package with proper entry points.
# TODO: Remove when DataPipeline has a proper pyproject.toml [project.scripts].
_EMSX_ROOT = Path(__file__).resolve().parents[1]
if str(_EMSX_ROOT) not in sys.path:
    sys.path.insert(0, str(_EMSX_ROOT))
    warnings.warn(
        "DataPipeline.__main__ sys.path hack is active. "
        "Install DataPipeline via pyproject.toml dependencies for proper isolation.",
        DeprecationWarning,
        stacklevel=2,
    )

from DataPipeline.config import Config
from DataPipeline.orchestration.core import run_full_pipeline

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _main() -> None:
    parser = argparse.ArgumentParser(description="EMSX DataPipeline")
    parser.add_argument("--once", action="store_true", help="Run full pipeline once and exit")
    parser.add_argument("--skip-bdib", action="store_true", default=True, help="Skip BDIB integration")
    parser.add_argument("--skip-ingest", action="store_true", default=True, help="Skip Excel ingestion")
    args = parser.parse_args()

    logger = logging.getLogger("DataPipeline")
    logger.info("DataPipeline CLI starting (once=%s)", args.once)

    if args.once:
        summary = run_full_pipeline(
            skip_bdib=args.skip_bdib,
            skip_ingest=args.skip_ingest,
            stage_marker_name="pipeline",
        )
        logger.info("Pipeline complete: %s", summary)
    else:
        logger.warning("No action specified. Use --once to run the pipeline.")


if __name__ == "__main__":
    _main()
