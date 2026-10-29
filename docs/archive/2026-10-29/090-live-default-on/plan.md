# 090 — D-6 定稿：实时列开关默认开启

> 父计划：`specs/057-execution-decision-loop/plan.md` 节点一出口判据第 7 条（呈现效果经用户打磨定稿）
> 分支：`090-live-default-on`（基线 `origin/main`）
> 用户确认（2026-10-27）：实时列保持三列；列顺序、覆盖率口径、未匹配位置、新鲜度阈值均按现状；**实时开关改为默认开启**。

## 1. 问题（是什么）

D-6 六项呈现选择中，前五项与现实现一致，第六项要求把 `EMSXVIEW_INTRADAY_STATE_ENABLED` 从默认关闭改为默认开启——否则节点一的「实时指标列」在生产默认配置下全是 `n/a`。

## 2. 方案（为什么这样做）

- 开关默认值 `false → true`；仍可用 `EMSXVIEW_INTRADAY_STATE_ENABLED=false` 回到四字段订阅（保留降级路径）；
- 默认开启意味着后端启动即订阅 `BID/ASK/LAST_PRICE/VOLUME/HIGH/LOW` 六个字段；这是订阅字段扩展，不增加请求类调用；
- 用子进程断言默认值（config 在导入时实例化 Settings 并校验 JWT_SECRET，进程内 reload 会污染全局）；
- 文档同步：节点一交付说明 §4 改为「已定稿」表、§5 限制更新、AGENTS/README 的 Beta 说明去掉「默认关闭」。

## 3. 落地（范围锁）

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `backend/api/config.py` | 改 | 默认 `true` + 注释指向 D-6 |
| 2 | `backend/api/services/market_state_service.py` | 改 | 开关 docstring |
| 3 | `backend/api/tests/test_market_state_service.py` | 改 | 子进程断言默认开启 |
| 4 | `docs/milestone-1-pretrade-board.md` | 改 | §4 定稿表（六项）+ §5 限制 |
| 5 | `AGENTS.md`、`README.md` | 改 | Beta 说明 |

## 4. 验收

1. 未设环境变量时 `settings.EMSXVIEW_INTRADAY_STATE_ENABLED is True`（子进程测试）；
2. 设 `false` 时端点返回 `enabled:false`（既有两态测试仍绿）；
3. 全量后端测试通过；
4. 文档六项定稿可逐条对照用户确认。
