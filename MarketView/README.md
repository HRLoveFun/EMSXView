# MarketView Module

> **Pre-Trade Analysis Module** · 🟡 **Scaffold** · Independent Microservice (port 8001)

> 成熟度分级定义见主 [README.md §0](../README.md#0-模块成熟度分级契约定义)。定级 Scaffold 的证据：仅 3 个端点、无自身测试目录；未实现清单：策略分析、选券支持、独立测试、SLA/运维文档。

---

## Overview

The **MarketView** module provides pre-trade market snapshot and intraday
feature analysis. It now runs as an independent FastAPI service.

## Architecture

```
MarketView/                      # Independent microservice
├── main.py                      # FastAPI app entry (:8001)
├── config.py                    # Service configuration
├── requirements.txt             # Python dependencies
└── routers/
    └── marketview.py            # API endpoints
```

## Deployment

### Standalone (microservice mode)
```bash
cd MarketView
pip install -r requirements.txt
python main.py                    # Starts on :8001
```

> MarketView runs as a standalone service only. The merge-mode integration
> in `backend/api/` has been removed (Phase B3).

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/marketview/snapshot` | Daily market snapshot with pool/filter/sort |
| `GET /api/marketview/intraday-features` | Intraday BDIB bar features per ticker |
| `POST /api/marketview/handoff/execution` | Publish candidates to ExecutionView |

## Dependencies

- `emsxview-platform-data` (pip editable install)
- Redis (for cross-process handoff in microservice mode)
- No Bloomberg EMSX session required
- No PostgreSQL required

## Data Flow

```
bdib_daily_summary (SQLite)
  → platform_data/adapters/market.py (MarketReferenceDataAdapter)
    → MarketView/routers/marketview.py (FastAPI endpoint)
      → frontend/src/modules/marketview/MarketViewModule.tsx (UI)
```

## Nginx Routing

```nginx
location /api/marketview/ {
    proxy_pass <MARKETVIEW_BASE_URL>/api/marketview/;   # 默认 http://localhost:8001，环境变量 MARKETVIEW_HOST / MARKETVIEW_PORT
}
```

---

*Status: Independent microservice with Redis handoff to main EMSXView service.*
*Last verified: 2026-09-11（端点清单提取自 `routers/marketview.py` 源码行号；"merge-mode 已移除"经 `backend/api` 全量 grep 核实属实——backend 无 marketview router 与 merge 消费点；未做运行时验证）*
