"""DataPipeline — independent data acquisition, processing, and storage subsystem.

This package owns all data ingestion, cleaning, enrichment, metrics computation,
and pipeline orchestration. It operates as an independent infrastructural subdomain.

Public API
----------
The following symbols form the **stable public surface** that external packages
should depend on. Importing from internal submodules directly (e.g.
``DataPipeline.storage.schema.columns``) is discouraged and may break without
notice across minor versions.

  * ``Config`` — single source of truth for pipeline configuration
  * ``ConnectionManager`` — centralized SQLite connection lifecycle
  * ``AccessTier`` — read/write access tier enumeration

See docs/spec/data-domain.md for the logical data domain boundaries.
"""

__version__ = "1.0.0"

# ── Stable public API exports ────────────────────────────────────────────
# P2-D7: External consumers should import from here rather than reaching
# into internal submodules (DataPipeline.storage.schema.columns, etc.).

from DataPipeline.config import Config
from DataPipeline.storage.connection import ConnectionManager, AccessTier
