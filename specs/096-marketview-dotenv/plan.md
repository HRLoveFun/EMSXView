# 096 — MarketView 读取仓库根 .env（统一配置入口）

> 触发：2026-10-27 配置 `EMSXVIEW_EXPORT_INBOX_DIR` 时发现 MarketView 只认进程环境变量，而 core backend 已 `load_dotenv()`
> 分支：`096-marketview-dotenv`

## 1. 问题

`MarketView/config.py` 的 `EXPORT_INBOX_DIR` 等常量在 import 时读 `os.getenv`，但**不加载根 `.env`**；core backend（`backend/api/main.py`）会 `load_dotenv()`。同一份 `.env` 对 core 生效、对 MarketView 不生效，配置行为不一致，也让「改 .env 即生效」的预期落空。

## 2. 方案

在 `MarketView/config.py` 顶部（任何 `os.getenv` 常量之前）加载仓库根 `.env`：

- 路径用 `Path(__file__).resolve().parents[1] / ".env"`（不硬编码盘符）；
- `python-dotenv` 缺失时静默跳过，保持「只认进程环境变量」的旧行为；
- 不引入新的必需依赖（`requirements.txt` 已有 python-dotenv 或走 ImportError 分支）。

## 3. 落地

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `MarketView/config.py` | 改 | `load_dotenv(根/.env)` |

## 4. 验收（本机实测）

根 `.env` 写入 `EMSXVIEW_EXPORT_INBOX_DIR=C:/Users/hrchen/EMSXViewData/emsx_inbox` 后，仅以 `python main.py` 启动（不带环境变量前缀）：

- `GET /api/marketview/pretrade-board` → `items=5`、`intent_source=export`、`coverage=80.0`、`unmatched=1`；
- `freshness` 返回 6 个数据集（真实 `intraday_manifest.json`）。
