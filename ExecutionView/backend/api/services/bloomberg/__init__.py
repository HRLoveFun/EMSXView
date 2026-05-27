"""Bloomberg EMSX Service package.

Backward-compatible re-export from services.bloomberg_adapter.

Future work: split the monolithic ~2700-line _adapter.py into:
  - connection.py   — session management, heartbeat, connect/disconnect
  - subscriptions.py — order/route/mktdata subscription loops & processing
  - order_ops.py     — create/modify/cancel orders (async methods)
  - route_ops.py     — route CRUD (cancel_route, modify_route, route_order)
  - data_query.py    — reference data, broker strategies, asset class queries
"""

from services.bloomberg_adapter import (  # noqa: F401
    BloombergEMSXService,
    configure,
    settings,
    repo_provider,
)
