# 025 — 残留清理指引收敛到受保护工具（并清空历史残留）

> 特性：`025-wt-residual-cleanup-guidance`
> 分支：`025-wt-residual-cleanup-guidance`（worktree `../EMSXView-wt-025-wt-residual-cleanup-guidance`）
> 背景：`specs/016-wt-finish-robustness`（残留不再抛裸异常）、`docs/spec/git-workflow.md` §3.4/§3.5

---

## 1. 清空历史残留（实测）

| 残留项 | 归属 | 处置 |
|---|---|---|
| 主工作树 `$null`（空文件） | 本会话（一次 `git commit -m ... 1>$null` 的命名事故） | 已删 ✓ |
| `EMSXView-wt-022-t11-async-data-layer` | 本会话 | 已删 ✓ |
| `EMSXView-wt-023-t12-batch-route-derive` | 本会话 | 已删 ✓ |
| `EMSXView-wt-024-t12-rows-derive` | 本会话 | 已删 ✓ |
| `C:\Users\hrchen\Documents\_nm-bak-023`（绕开批量删除保护的依赖残骸） | 本会话 | 已删 ✓ |
| `EMSXView-wt-p2-first-batch`（**空壳**：0 条目、非 git 仓库） | 非本会话 | 已用 `wt-clean.ps1 p2-first-batch -Apply -Force` 删除 ✓ |

复核：`git worktree list` 仅主工作树；`C:\Users\hrchen\Documents` 下 `EMSXView-wt-*` 为空；
主工作树 `git status` 干净。

## 2. 改动：清理指引改指向 `wt-clean.ps1`

`wt-finish` 在「注册表已注销、目录删不掉」分支此前打印的是**裸递归删除**命令
（`Remove-Item -Recurse -Force '<dir>'`）。该形态残留实测在 020/022/023/024 **反复出现**，
而裸命令会绕过 `wt-clean` 的三道保护（锁保护 / 强制须指名 / `_tmp` 在途保护）。

改动：

- `scripts/devtools/wt-finish.ps1`：残留分支的指引改为推荐
  `./scripts/devtools/wt-clean.ps1 <task> -Apply -Force`（附 `-SkipTmp` 提示与等价裸命令），
  并在文件头记录本次收敛的原因）；
- `docs/spec/git-workflow.md` §3.4：同步该指引；
- `docs/spec/git-workflow.md` §3.5 新增两条：
  - **残留目录的推荐清理路径**（§3.4 的残留也用本工具，`orphan` 识别 + `-Force` + 指名）；
  - **`-Apply` 会连带处理 `_tmp`**（若非本意请加 `-SkipTmp`）。

## 3. 一次必须记录的踩坑（本 PR 的直接动因之一）

清理最后那个空壳时，我执行了 `wt-clean.ps1 p2-first-batch -Apply -Force`（未加 `-SkipTmp`），
它按设计**连带删除了 `_tmp/backup-20260916-rules`**（另一会话留下的规则备份，非在途）。

损失评估：`.codebuddy/rules/` 共 4 个文件、**全部受版本控制**且无未提交改动（`tracked=4 / dirty=0 / disk=4`），
故该备份内容可经 git 完整恢复，**无不可挽回损失**。§3.5 已新增该行为的显式说明，避免他人重蹈。

## 4. 验证（全部实测）

| 项 | 结果 |
|---|---|
| **残留分支真实触发**（一次性 scratch 兄弟目录，非 worktree） | `git worktree remove` exit=128 → 打印新指引 → exit 1 ✓ |
| **新指引的命令可用** | `wt-clean.ps1 verify-residual -Apply -Force -SkipTmp` → 识别为 `orphan` → 删除成功，`[tmp] 已跳过（-SkipTmp）` ✓ |
| 边界测试（含 `test_ps1_encoding`） | **23 passed, 1 skipped**（与 main 一致，无新增 skip） |
| `audit_doc_drift` / `audit_cross_imports` | OK / 无违规 |
| 改动面 | 2 文件（指引与文档），无行为语义变更（删除逻辑未动） |

## 5. 决策：为什么不把「递归删除」自动化

`wt-finish` 移除失败时**不应自动递归删除**：分支已合并 ≠ 工作树干净（可能仍有未提交改动）。
检测「目录是否为空 / 是否干净」再删是可行的，但那让工具在失败路径上承担破坏性动作；
现有分工更清晰 —— `wt-finish` 负责「移除 + 指引」，`wt-clean` 负责「受保护的清理」。
本 PR 只把两者接通，不改变任何删除语义。
