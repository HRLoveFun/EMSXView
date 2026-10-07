# 042 — S12：PM 授权意图与剩余量跟踪

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第三波补充 · 买方工作流延伸）
> 分支：`042-authorization-intent`（worktree `../EMSXView-wt-042-authorization-intent`）
> 依据：伞计划第三波定义中的「PM 授权量与剩余量跟踪」——报告点名的买方核心需求：
> 「PM 要买 100 万股，允许今天完成 60 万股；其中 30 万股正在券商算法中执行。
> 系统应知道剩余授权是多少，而不仅显示订单还剩多少股。」

## 1. 问题

系统此前只显示订单/路由的剩余量，没有 PM 投资决策层的授权概念——
「数量与敞口」约束（已成交、在途与新增合计是否超出 PM 授权）无人回答。

## 2. 方案（P2 三栏）

- **理论依据**：授权是投资决策层数据（symbol+side+portfolio 维度的数量上限）；执行占用以父单承诺量计（父单创建即占用，含计划中切片），剩余 = target − committed——与报告场景语义一致。
- **技术方案**：
  - `models/authorization.py`（新增）：`AuthorizationIntent` 表（Base.metadata.create_all 自动建表，无迁移）。
  - `repositories/authorization.py` + provider（create/load，S8 模式复用）。
  - `services/authorization_service.py`：`compute_remaining`（父单经 orders_projection payload 按 order_id 关联补 symbol/side/portfolio——投影缺失排除并告警）；`check_authorization` 三态（not_covered / exceeded / ok）。
  - `routers/authorizations.py`（新增）：POST（admin）/GET（view，含剩余量）。
- **检验方法**：`test_authorization_tracking.py` 六用例：基础剩余量；portfolio 不限合并；side 不匹配；投影缺失排除；三态检查；端点降级语义。

## 3. 范围锁

- `backend/api/models/authorization.py`、`repositories/authorization.py`（新增）
- `backend/api/service_provider.py`（create_authorization/load_authorizations）
- `backend/api/services/authorization_service.py`（新增）
- `backend/api/routers/authorizations.py`（新增）、`backend/api/main.py`（router 注册）
- `backend/api/tests/test_authorization_tracking.py`（新增）
- `specs/042-authorization-intent/plan.md`（本文件）

## 4. 本次不做（转入 043）

- 下单入口挂接 `check_authorization` 硬校验（route_order / confirm_proposal）——独立子任务 043。
- 授权的多维度扩展（账户/市场/价格偏离限制）。

## 5. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 系统知道剩余授权 | compute_remaining 用例 | CI |
| 占用含计划中切片 | committed ≠ filled 断言 | CI |
| portfolio 维度语义 | 不限/精确两用例 | CI |
| 下单入口可查询授权态 | check_authorization 三态 | CI |
| 既有测试不回归 | 280 → 286 passed | CI |
