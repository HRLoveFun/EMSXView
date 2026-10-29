# 040 — S10：可配置用户源（EMSXVIEW_USERS 替代硬编码 DEMO_USERS）

> 父计划：`specs/029-trading-reliability-hardening/plan.md`（第三波 · 授权与流程闭环 · S10 / B8）
> 分支：`040-auth-user-source-config`（worktree `../EMSXView-wt-040-auth-user-source-config`）

## 1. 问题

报告批评：认证身份源仍使用 `DEMO_USERS` 硬编码（trader1/trader2/admin 同密码
"password"，`auth.py:46`）——多人使用场景下不可接受。LDAP/AD 等上游授权源
未到位，但硬编码演示账号不应是唯一选择。

## 2. 方案（P2 三栏）

- **理论依据**：身份源必须可配置且回退路径诚实可见——生产部署未配置用户源时应收到启动告警，而非静默沿用演示账号。
- **技术方案**：
  - `config.EMSXVIEW_USERS`（JSON 数组：username / password_hash(bcrypt) / full_name / role；config 注释附 bcrypt 生成命令）。
  - `auth._load_config_users()`：导入期解析，坏 JSON / 缺字段 → ERROR 可见并跳过；配置生效 → INFO 记录用户数；**未配置 → WARNING 明示 DEMO_USERS 仍生效**。
  - `authenticate_user`：配置用户优先，未命中回落 DEMO_USERS（现有部署零破坏）。
- **检验方法**：`test_auth_user_source.py` 五用例：配置登录成功+错密码拒绝；未命中回落；坏 JSON 回落+ERROR；缺字段跳过；空配置告警+DEMO_USERS 生效。

## 3. 范围锁

- `backend/api/auth.py`（_load_config_users + authenticate_user）
- `backend/api/config.py`（EMSXVIEW_USERS 字段）
- `backend/api/tests/test_auth_user_source.py`（新增）
- `specs/040-auth-user-source-config/plan.md`（本文件）

LDAP/AD 集成属上游依赖到位后的独立演进（换 `_load_config_users` 实现即可，
authenticate_user 优先级结构不变）。

## 4. 验收（P4）

| 需求 | 覆盖 | 结果 |
|---|---|---|
| 身份源可配置（非硬编码） | 配置登录用例 | CI |
| 回退路径诚实可见 | 空配置 WARNING / 坏 JSON ERROR 用例 | CI |
| 现有部署零破坏 | 未命中回落用例 | CI |
| 既有测试不回归 | 269 → 274 passed | CI |
