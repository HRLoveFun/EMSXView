# 223 — 固定 Node 22（审计 A12）

> 来源：`specs/057-execution-decision-loop/audit-remediation-2026-10-25.md` **A12（E3）**
> 分支：`223-node-pin`（worktree `../EMSXView-wt-223-node-pin`，基于 `origin/main`）

## 问题

仓库未声明 Node 版本：根与 `frontend` 的 `package.json` 都没有 `engines`，也没有 `.nvmrc`。不同机器用不同 Node 大版本，依赖解析与 CI 可能漂移。

## 方案

- 根 `package.json` 与 `frontend/package.json` 增加 `engines.node = ">=20.19 <23"`（与审计口径一致）。
- 新增仓库根 `.nvmrc`，内容 `22`。
- `README.md` 的环境要求写明 Node 22 与 `.nvmrc`。

## 验收

- 两个 `package.json` 为合法 JSON 且 `engines` 正确；
- CI 使用 Node 22；本机其他版本按 `.nvmrc` 切换（未启用 engine-strict，不阻断安装）；
- `python scripts/doc_check.py` 退出码 0；
- CI 在 Node 22 下通过。

## 范围锁

- `package.json`、`frontend/package.json`、`.nvmrc`、`README.md`、
  `specs/057-execution-decision-loop/tasks.md`、`specs/223-node-pin/plan.md`

**不做**：不升级依赖、不改 CI 矩阵、不引入 Volta/nvm 安装脚本。
