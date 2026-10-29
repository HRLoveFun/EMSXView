# MarketView 实时字段测试记录（mktdata 可用性矩阵）

> L3 | 权威：实时字段可用性矩阵与复测 SOP | 不权威：实时列当前默认值（见 `README.md` §0）

> **定位**：MarketView 实时列（`Last` / `Chg %` / `Bid` / `Ask` / `Spread bps` / `Live Vol` / `Live Vol ÷ ADV20`）的**字段选型依据**与**复测基线**。改实时列之前先读本文；改完按 §6 的清单逐项落位，按 §8 复测并在本文登记。
>
> **结论有效范围**：字段可用性 = f(字段, 市场, 交易时段, 终端权限)。本文结论限定于下表记录的时刻与终端；跨时段必须复测（§8）。
>
> **上游文档**：[docs/blpapi-api-modules.md](blpapi-api-modules.md) §15（订阅链路、契约与端点）；本文只覆盖「字段能不能用、怎么维护字段列表」。

## 1. 探针元数据

| 项 | 记录 A（基线） | 记录 B（交叉复核） |
|---|---|---|
| 探针时刻（本机 UTC+8） | 2026-10-28 14:35 | 2026-10-28 14:17 |
| 观察窗口 | 30 s | 20 s |
| 样本数 | 34（每市场 1 个） | 67（每市场 1–2 个） |
| 样本来源 | `tca_route_summary.Exchange` 全量取值（34 个交易所），每市取路由数最多的标的 | 同上，取前 2 个 |
| 终端 | 本机 Bloomberg 终端 `localhost:8194`，blpapi 3.26.7.1 | 同左 |
| 工具 | `scripts/diagnose/blpapi_mktdata_probe.py --tickers-file scripts/diagnose/mktdata_market_samples.txt --seconds 30` | 同左（`--seconds 20`，临时样本集） |
| 时段状态 | 沪深港通/港股/韩股/印股/马股/印尼/新加坡盘后段在交易；日股收市；欧股盘前（法兰克福/赫尔辛基零星跳动）；**美股、加拿大、澳洲、新西兰、巴西、墨西哥、南非休市** | 同左（早 18 分钟） |

判定口径：单元格 `-` = 元素缺失（未推送/无权限）、`null` = 元素存在但无值、数字 = 有值。

## 2. 稳定结论（两次记录一致）

| 字段 | 覆盖 | 结论 |
|---|---|---|
| `BID` / `ASK` / `LAST_PRICE` / `OPEN` / `HIGH` / `LOW` / `MID` | 31–33 / 33 | 可用；**休市市场返回上一交易日镜像值**，不是「实时在跳」 |
| `PREV_CLOSE_VALUE_REALTIME` | 33 / 33 | **全市场可用** → 实时涨跌幅唯一可靠来源 |
| `CHG_PCT_1D` / `NET_CHG_PCT_1D` / `PX_CLOSE_1D` | 0 / 33 | mktdata 不推送（第二次确认，与 2026-10-28 美股单例一致） |
| `VOLUME_AVG_5D` / `VOLUME_AVG_20D` | 0 / 33 | 不推送 → 参与率分母改用日度 `bdib_daily_summary` 的 ADV20 |
| `PX_ROUND_LOT_SIZE` | 0 / 33 | 不推送 → 整手走 `//blp/refdata`（既有实现） |
| `VWAP` | 20 / 33 触及，仅 AU/IJ/IN/JP/KS/MK/NZ/SP 有真实值 | EU/US 返回 `0.00`、HK/CN/BZ/MM 缺失 → **不可用作基准价** |
| `BID_SIZE` / `ASK_SIZE` | 29–31 / 33 | 丹麦（DC）、瑞典（SS）整体缺失；IT/SW 个别缺 → 不做规模推断 |

## 3. 分市场矩阵（记录 A，2026-10-28 14:35，30 s）

| 市场 | 样本 | 事件数 | 窗口内跳动 | 价量核心 | 交易量尺寸 | 前收 | VWAP | 最新价 | 备注 |
|---|---|---:|---|---|---|---|---|---:|---|
| AU | `BHP AU Equity` | 3 | 否 | ok | ok | ok | 58.29 | 58.04 |  |
| AV | `EBS EU Equity` | 3 | 否 | ok | ok | ok | – | 107.80 |  |
| BB | `KBC EU Equity` | 1 | 否 | 缺 VOLUME | ok | ok | – | 115.80 |  |
| BZ | `VALE3 BZ Equity` | 1 | 否 | ok | ok | ok | – | 63.00 |  |
| C1 | `600183 CH Equity` | 356 | 是 | ok | ok | ok | – | 101.46 | 沪港通盘中 |
| CN | `AEM CN Equity` | 1 | 否 | ok | ok | ok | – | 253.75 | 加拿大休市 |
| DC | `DSV DC Equity` | 4 | 否 | ok | 缺 BID/ASK | ok | 0.00 | 1394.00 | VWAP 占位 0.00 |
| FH | `NOKIA EU Equity` | 1 | 否 | ok | ok | ok | 8.10 | 8.14 |  |
| FP | `SU EU Equity` | 3 | 否 | ok | ok | ok | – | 244.90 |  |
| GA | `ETE EU Equity` | 1 | 否 | ok | ok | ok | 15.63 | 15.65 |  |
| GR | `SAP EU Equity` | 12 | 是 | ok | ok | ok | 211.85 | 212.00 | 欧股盘前零星跳动 |
| HK | `2899 HK Equity` | 31 | 否 | ok | ok | ok | – | 28.44 |  |
| ID | `KSP EU Equity` | 6 | 否 | 缺 VOLUME | ok | ok | – | 95.00 |  |
| IJ | `TLKM IJ Equity` | 52 | 否 | ok | ok | ok | 2061.69 | 2050.00 |  |
| IM | `UCG EU Equity` | 1 | 否 | ok | ok | ok | – | 74.46 |  |
| IN | `ICICIBC IN Equity` | 78 | 是 | ok | ok | ok | 1369.57 | 1375.50 |  |
| IT | `NICE IT Equity` | 3 | 否 | 缺 BID | 缺 BID | ok | 0.00 | 37750.00 | 无 BID（单边报价）；VWAP 占位 0.00 |
| JP | `6857 JP Equity` | 3 | 否 | ok | ok | ok | 34916.19 | 34930.00 | 日股已收市 |
| KS | `005930 KS Equity` | 1804 | 否 | ok | ok | ok | 237932.83 | 242000.00 |  |
| LN | `RIO LN Equity` | 1 | 否 | ok | ok | ok | 0.00 | 6400.00 | VWAP 占位 0.00 |
| MK | `PMAH MK Equity` | 24 | 是 | ok | ok | ok | 6.77 | 6.80 |  |
| MM | `GMEXICOB MM Equity` | 3 | 否 | ok | ok | ok | – | 233.84 |  |
| MUMBAI | `TVSLIN/P MUMBAI Equity` | – | – | – | – | – | – | – | 订阅失败 `BAD_SEC`（见 §5） |
| NA | `ASML EU Equity` | 1 | 否 | ok | ok | ok | – | 1472.60 |  |
| NO | `NHY NO Equity` | 4 | 否 | ok | ok | ok | 0.00 | 68.70 | 买卖价含 0.00（休市镜像）；VWAP 占位 0.00 |
| NZ | `AIA NZ Equity` | 3 | 否 | ok | ok | ok | 8.36 | 8.34 |  |
| PL | `GALP EU Equity` | 1 | 否 | 缺 VOLUME | ok | ok | – | 20.44 |  |
| PW | `KGH PW Equity` | 1 | 否 | ok | ok | ok | 0.00 | 305.55 | VWAP 占位 0.00 |
| SJ | `ANG SJ Equity` | 1 | 否 | ok | ok | ok | 0.00 | 143190.00 | VWAP 占位 0.00 |
| SM | `SAN EU Equity` | 2 | 否 | ok | ok | ok | – | 11.32 |  |
| SP | `DBS SP Equity` | 48 | 否 | ok | ok | ok | 74.15 | 74.10 |  |
| SS | `VOLVB SS Equity` | 4 | 否 | ok | 缺 BID/ASK | ok | 0.00 | 309.90 | VWAP 占位 0.00 |
| SW | `ABBN SW Equity` | 3 | 否 | 缺 BID | 缺 BID | ok | 0.00 | 71.50 | 买卖价含 0.00；MID=0.00；无 BID；VWAP 占位 0.00 |
| US | `NVDA US Equity` | 4 | 否 | ok | ok | ok | 0.00 | 217.94 | 美股休市；VWAP 占位 0.00 |

`窗口内跳动 = 是` 的 4 个市场（GR/C1/IN/MK）与「事件数 > 10」的市场，就是探针时刻真正在交易的市场；其余为镜像。

## 4. 分时段与镜像行为

- **休市 ≠ 无数据**：休市市场返回完整镜像（价、量、高开低、前收），所以「字段有值」不能当作「行情在跳」。判断时段必须看窗口内 `LAST_PRICE` 是否变化。
- **镜像可能分批到达、字段覆盖不稳定**：同一批标的在 14:17（记录 B）与 14:35（记录 A）两次探针中，`VOLUME` 覆盖从 33/33 变为 30/33（BB/ID/PL 缺）。因此「单次窗口缺某个字段」不构成市场级结论，需二次确认；反之，前端必须允许任意字段缺失并显式回落。
- **休市镜像会出现非法价格**：`SW ABBN` 实测 `ASK=0.00`、`MID=0.00`，`NO NHY` 买卖价含 0.00。价差/中间价计算必须保留 `<= 0 → None` 的守卫，不能只看元素是否存在（现实现：`market_state_service._spread_bps`）。
- **VWAP 的时段性未验证**：EU/US 在休市时段为 `0.00`，开盘后是否变为真实值**尚未验证**（§8 待办）；在验证前不得把 `VWAP` 引入实时列。

## 5. 现行实时字段清单（契约 ↔ 显示）

契约：`platform_data/contracts/market_contracts.py::MarketStateTickerState`（`MARKET_STATE_SCHEMA_VERSION = "market-state-v2"`）；前端镜像：`MarketView/module/types.ts`。

| 契约字段 | Bloomberg 来源 | 计算 | MarketView 显示位置 | 缺失回落 |
|---|---|---|---|---|
| `bid` / `ask` | `BID` / `ASK` | 直取 | 池板 `Bid` / `Ask`（绿/红） | `n/a` |
| `last` | `LAST_PRICE` | 直取 | 池板 `Last`、快照表 `Last` | `n/a` |
| `pct_change_1d` | `PREV_CLOSE_VALUE_REALTIME` | `CHG_PCT_1D` 优先（实测不推送）→ `LAST ÷ 前收 − 1`，2 位 | 池板 `Chg %`、快照表 `Chg %`（涨绿跌红） | `—` |
| `spread_bps` | `BID` / `ASK` | `(ask − bid) / mid × 1e4`，`bid/ask ≤ 0` 或 `ask < bid` → `None` | 池板 `Sprd bps` | `n/a` |
| `spread_vs_baseline_bps` | `BID`/`ASK` + 日度基线 | `spread − baseline.spread_proxy_bps`，超阈值打 `SPREAD_VS_BASELINE_WIDE` 告警 | 池板告警徽标 | 不显示 |
| `volume` | `VOLUME` | 直取 | 池板 `Live Vol`；`Live Vol ÷ ADV20`（分母取日度 `adv_20d`） | `—` / `n/a` |
| `high` / `low` | `HIGH` / `LOW` | 直取 | 契约保留，暂未显示 | — |
| `cumulative_volume_ratio` | — | DL-09 预期曲线未就绪 | 盘前单面板 `Vol vs base` | `n/a` |

已确认**不进入**契约的字段（避免重复试错）：

| 字段 | 否决原因 | 证据 |
|---|---|---|
| `CHG_PCT_1D` / `NET_CHG_PCT_1D` / `PX_CLOSE_1D` | mktdata 不推送 | 记录 A/B 全市场 0 触及 |
| `VOLUME_AVG_5D` / `VOLUME_AVG_20D` | 不推送；参与率用日度 ADV20 更稳定 | 同上 |
| `PX_ROUND_LOT_SIZE` | 不推送；整手走 refdata | 同上 |
| `VWAP` | 仅部分市场有真实值，EU/US 为 `0.00` | 记录 A：20/33 触达，8 个市场有真值 |
| `BID_SIZE` / `ASK_SIZE` | DC/SS 整体缺失，取样不足以支撑规模推断 | 记录 A/B 一致 |
| `MID` | SW/IT 等市场为 `0.00` | 记录 A |

数据质量问题（与订阅无关，记录备查）：

- `TVSLIN/P MUMBAI Equity`（`Exchange=MUMBAI`，全库 5 条路由）订阅返回 `SubscriptionFailure / BAD_SEC / Unknown/Invalid Security` —— EMSX 交易所代码不对应可用的 BLPAPI 后缀，需订单侧确认正确代码。

## 6. 更新实时数据列表的操作清单

新增/替换一个实时字段，按数据流顺序改 7 处（缺一处即「字段有值但界面不显示」或「界面读不到」）：

1. `backend/api/services/bloomberg/enrichment.py`
   - `_MKTDATA_BASE_FIELDS`（订单富化用）或 `_MKTDATA_INTRADAY_FIELDS`（盘中状态用）加入字段名；
   - `parse_intraday_quote` 的数值白名单同步加入（未列入的字段即使推送也不会进缓存）。
2. `backend/api/services/bloomberg/adapter.py`：新增缓存容器时补只读代理（`intraday_quotes` / `price_changes` 的同类）。
3. `backend/api/services/market_state_service.py`：`build_market_state_snapshot` 里映射到契约字段；派生逻辑写成独立小函数（如 `_pct_change_1d`），保持「缺失返回 `None`，不猜 0」。
4. `platform_data/contracts/market_contracts.py`：`MarketStateTickerState` 加字段 + `MARKET_STATE_SCHEMA_VERSION` 升版（v3、v4…），并在文件头注明新增原因。
5. `MarketView/module/types.ts`：镜像同一字段（契约与前端类型必须逐字段一致）。
6. `MarketView/module/components/`：`snapshot-table.tsx` / `pool-board-panel.tsx` 加列，缺失回落统一走 `—` / `n/a`；派生比率放 `lib/workspace.ts`（有单测）。
7. 测试与文档：
   - `backend/api/tests/test_market_state_service.py`（解析、派生、回落、越界）；
   - `MarketView/module/*.test.tsx`（列渲染 + 缺失回落）；
   - 本文 §5 与 [blpapi-api-modules.md](blpapi-api-modules.md) §15.3 同步。

验收：`pytest backend/api/tests` 全绿 → `npx tsc -b` → `vitest run` → 起服务后用 §8 命令复测一次，确认新字段在目标市场有值、在缺失市场回落为 `n/a`。

## 7. 复测 SOP

```powershell
# 1) 全市场基线（34 个实际交易市场）
python scripts/diagnose/blpapi_mktdata_probe.py --tickers-file scripts/diagnose/mktdata_market_samples.txt --seconds 30 --json _tmp/probe.json

# 2) 单市场/单标的排查
python scripts/diagnose/blpapi_mktdata_probe.py --tickers "AAPL US Equity,700 HK Equity" --seconds 60
```

判读顺序：①看「窗口内 LAST_PRICE 有跳动」确认该市场在不在交易 → ②看字段覆盖 → ③对异常市场用 ② 单独复测（排除镜像分批）。

必须复测的触发条件：

- 新增市场（`tca_route_summary.Exchange` 出现新值）；
- 新增/替换实时字段；
- 关键时段变化：**美股开盘 21:30 HKT**、**欧股开盘 15:00 HKT**、亚股早盘 09:30 HKT；
- 终端权限或 Bloomberg 版本变化（当前 blpapi 3.26.7.1）。

复测后在本文件 §1 追加一行记录（时刻/窗口/样本数/时段状态），并更新 §2、§3 的结论；结论变化需在 PR 说明中写清「旧口径 → 新口径」。

## 8. 尚未覆盖（待补测）

| 待测项 | 原因 | 期望验证 |
|---|---|---|
| 美股/欧股开盘时段的全字段覆盖 | 两轮探针均在美股休市、欧股盘前 | `VWAP` 是否转为真实值；`VOLUME` 是否稳定推送 |
| `BID_SIZE` / `ASK_SIZE` 开盘时段表现 | 休市镜像下 DC/SS 整体缺失 | 是否为休市特有现象 |
| `MUMBAI` 后缀的正确 BLPAPI 代码 | 订阅直接 `BAD_SEC` | 与订单侧确认交易所代码映射 |
| 逐笔级字段（如需更细粒度） | 当前只用快照类字段 | 是否需要 `LAST_TRADE`/`TRADE` 等 tick 级订阅 |
