# MarketView Module

> **Market Trend View** · 🟢 **Beta** · Independent Microservice (port 8001)

> 成熟度分级定义见主 [README.md §0](../README.md#0-模块成熟度分级契约定义)。定级 Beta 的证据：8 个端点、8 个测试文件 / 74 例、已知限制清单（[docs/milestone-1-pretrade-board.md](../docs/milestone-1-pretrade-board.md) §5）。

---

## 使命

**检查、更新股票池，监测股票池内标的**，把「今天该关注哪些票、这些票的意图是什么、执行难度多大、成本大概多少」算清楚。

- 观察轴：**标的 × 交易日**（市场走势）。
- **不碰下单路径**：不发送、不修改、不撤销订单/路由，不写任何库；只读数据、只做提示。
- 池内标的的量价指标、执行难度与成本参考值同屏展示（DL-29，`GET /api/marketview/pool-board`）；成本按「100 万美元名义额 → qty ÷ ADV20 参与率」估算，标注为池内横向比较而非订单级预测。

## 与 ExecutionView 的分工

两个视图共享同一批行情、基线与意图数据，但观察轴不同，**并存且不可互相替代**：

| | MarketView | ExecutionView |
|---|---|---|
| 观察轴 | 标的 × 交易日 | 订单/路由 × 执行区间 |
| 回答 | 该关注哪些票、意图是什么、难度多大、成本多少 | 这笔（这批）委托正在做得怎么样、偏离多少 |
| 数据 | 只读快照、基线、盘中特征 | 复用 MarketView 数据 + 订单生命周期 |
| 动作 | 只做提示 | 发送、修改订单/路由 |

## Architecture

```
MarketView/                      # Independent microservice
├── main.py                      # FastAPI app entry (:8001)
├── config.py                    # Service configuration
├── requirements.txt             # Python dependencies
├── routers/
│   ├── marketview.py            # snapshot / intraday-features / handoff
│   ├── export_orders.py         # pre-trade-orders（EMSX 导出解析）
│   ├── pretrade.py              # pretrade-board（意图 + 基线 + 状态 + 成本）
│   ├── baseline.py              # daily-baseline（60 日稳健分布）
│   ├── regime.py                # market-regime（事件与市场状态）
│   └── pool_board.py            # pool-board（固定池量价/难度/成本同屏，DL-29）
├── module/                      # 前端模块（仓库根级，与 frontend/ 平级）
└── tests/                       # 8 个测试文件 / 74 例
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
| `GET /api/marketview/snapshot` | 股票池检查与日度市场快照（池 / 筛选 / 排序） |
| `GET /api/marketview/intraday-features` | 盘中 BDIB bar 特征（按交易所本地时段分桶） |
| `GET /api/marketview/pre-trade-orders` | EMSX 导出解析与 PM 意图映射（DL-01） |
| `GET /api/marketview/pretrade-board` | 盘前单四路装配：意图 + 基线 + 状态 + 预期成本（DL-14） |
| `GET /api/marketview/daily-baseline` | 60 日稳健个股基线（DL-10） |
| `GET /api/marketview/market-regime` | 市场级状态与事件标记（DL-11） |
| `GET /api/marketview/pool-board` | 固定池池板：量价 + 难度分位 + 成本参考值（DL-29） |
| `POST /api/marketview/handoff/execution` | 向 ExecutionView 发布提示性候选（不触发下单） |

## Local dev with the React shell

The Vite dev server proxies `/api/marketview/*` to this service, so no Nginx is needed locally:

- proxy target = `VITE_MARKETVIEW_URL`（默认 `http://127.0.0.1:8001`；用 `127.0.0.1` 而非 `localhost`，避免 Node 把 `localhost` 解析成 IPv6 `::1` 而服务只监听 IPv4）
- core backend（`:3000`）不挂载 `/api/marketview/*`——只启动 core 时该页会全部 404

```bash
# 终端 1：MarketView
cd MarketView && python main.py

# 终端 2：前端壳
cd frontend && npm run dev
```

**鉴权**：受保护端点（`pool-board`、`handoff` 等）校验 Bearer JWT，密钥与 core backend 共用 `JWT_SECRET`。读取顺序为仓库根 `.env` → `backend/.env`（回退，兼容密钥只写在后端配置的既有部署）。默认 fail-closed（无密钥/无 token 一律 401）；本地开发可在仓库根 `.env` 设 `BYPASS_AUTH=true` 免注入 token，语义与 core backend 一致，生产必须保持 `false`。

生产环境由 Nginx 把同一前缀转发到 `MARKETVIEW_BASE_URL`（见下）。

## Dependencies

- `emsxview-platform-data` (pip editable install)
- Redis (for cross-process handoff in microservice mode)
- No Bloomberg EMSX session required
- No PostgreSQL required

## Data Flow

```
bdib_daily_summary / bdib_market_snapshot / 盘中库（SQLite，只读）
  → platform_data/adapters/（market / baseline / events）
    → MarketView/routers/*.py（FastAPI endpoint）
      → MarketView/module/MarketViewModule.tsx（UI，仓库根级模块）
        → handoff 提示性候选 → ExecutionView
```

## Nginx Routing

```nginx
location /api/marketview/ {
    proxy_pass <MARKETVIEW_BASE_URL>/api/marketview/;   # 默认 http://localhost:8001，环境变量 MARKETVIEW_HOST / MARKETVIEW_PORT
}
```

---

*Status: Independent microservice with Redis handoff to main EMSXView service.*
*Last verified: 2026-10-27（端点清单经 `MarketView/routers/*.py` 全量 grep 核实；成熟度与测试计数取自主 README §0）*
