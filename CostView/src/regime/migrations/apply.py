"""
DEPRECATED — Migration runner moved to DataPipeline.src.storage.schema.migrations.apply.

This module re-exports ``apply_pending`` for backward compatibility.
New code should import from:
    DataPipeline.src.storage.schema.migrations.apply

Usage (CLI):
    python -m DataPipeline.src.storage.schema.migrations.apply
"""
from __future__ import annotations  # noqa: I001 — keep at top

import warnings
from typing import List

from DataPipeline.src.storage.schema.migrations.apply import apply_pending  # noqa: F401

warnings.warn(
    "CostView.src.regime.migrations.apply is deprecated — "
    "import from DataPipeline.src.storage.schema.migrations.apply instead.",
    DeprecationWarning,
    stacklevel=2,
)


def main(argv: List[str] | None = None) -> int:
    """Deprecated: delegate to the consolidated CLI entry point."""
    from DataPipeline.src.storage.schema.migrations.apply import main as _main  # noqa: PLC0415
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
