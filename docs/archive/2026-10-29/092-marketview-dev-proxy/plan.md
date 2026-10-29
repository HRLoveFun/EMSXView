# 092 — 本地 dev 打通 MarketView 前端（Vite 代理）

> 父计划：`specs/057-execution-decision-loop/plan.md` 节点一出口判据（表格可用、覆盖率/新鲜度可见）
> 分支：`092-marketview-dev-proxy`（基线 `origin/main`）

## 1. 问题（是什么）

`frontend/vite.config.ts` 只有 `/api` → `:3000` 一条代理，而 **core 后端不挂载 `/api/marketview/*`**（MarketView 是独立微服务 :8001）。本地 `npm run dev` 下 MarketView 页面所有请求 404，节点一的盘前单/实时列无法在浏览器验收——只有 Nginx 部署环境才能用。

## 2. 方案（为什么这样做）

- 在 Vite 代理中加 `/api/marketview` → `VITE_MARKETVIEW_URL`（默认 `http://localhost:8001`）；
- **必须排在 `/api` 之前**：Vite 按定义顺序匹配，宽前缀会先吞掉；
- 新增 `VITE_MARKETVIEW_URL` 环境变量（留空即默认），生产仍由 Nginx 转发同前缀，行为不变；
- 顺手清掉 `.env.example` 里已失效的 `VITE_USE_MOCK`（AGENTS §14 已列失效，无消费点）。

## 3. 落地（范围锁）

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `frontend/vite.config.ts` | 改 | `marketviewTarget` + `/api/marketview` 代理（在 `/api` 前） |
| 2 | `frontend/.env.example` | 改 | 新增 `VITE_MARKETVIEW_URL`；移除失效 `VITE_USE_MOCK` |
| 3 | `AGENTS.md` §11.5 | 改 | 前端环境变量表补一行 |
| 4 | `MarketView/README.md` | 改 | 端点表补 4 个；新增「Local dev with the React shell」 |
| 5 | `docs/milestone-1-pretrade-board.md` | 改 | 新增 §5「前端验收步骤（本地）」：启动顺序、数据前提、6 个检查点 |

## 4. 验收（本机实测）

1. 起 MarketView（:8001）与 `npm run dev`（:5274），`curl http://localhost:5274/api/marketview/pretrade-board` → **200**，返回体含 `intent_source`、`freshness`（真实读取 `D:\db\intraday\intraday_manifest.json`）；
2. `npm run typecheck` / `lint` / `lint:modules` 全 0；
3. `npm run test` → 28 files / 214 passed。
