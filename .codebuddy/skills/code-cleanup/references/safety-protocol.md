# 删除安全协议（Safety Protocol）

> **本文件是本 skill 的最高优先级约束。** 与规则集冲突时，以本文件为准。
> 关联：[`refactoring-methodology.md`](../../../docs/spec/refactoring-methodology.md)（行为保全优先）、
> [`plan-design-principles.md`](../../../docs/spec/plan-design-principles.md) P1（数据零受损）、
> [ADR-0014](../../../docs/spec/adr/0014-dead-code-cleanup.md)（死代码清理实践）。

---

## 一、三条红线

| 红线 | 含义 | 违反示例 |
|---|---|---|
| **行为保全优先** | 没有测试保护网或人工确认，不得删除生产代码 | 看到 `CL-01` 命中就直接 `rm` |
| **数据零受损** | 清理只作用于代码树；绝不触碰数据库 | 顺手 `DROP TABLE` / `VACUUM` / 删 `*.db` |
| **可回退** | 每批独立提交、批间测试全绿 | 一次性删 70 个文件 + 改 20 处文档 |

---

## 二、删除前的三轮质询（逐条候选都要过）

### 第一轮：动态引用核查

静态图看不见的引用方式，全部要查：

| 方式 | 检索命令 |
|---|---|
| 字符串反射 | `rg "getattr\(|import_module\(|__import__\(|globals\(\)|locals\(\)"` |
| 注册表/字典装配 | `rg "\"<name>\"|'<name>'"`（配置表、路由表、命令表、DI 容器） |
| 子进程调用 | `rg "subprocess|<name>\.py"` |
| CLI 入口 | 文件名是否 `cli.py` / `*_cli.py` / `__main__.py` / `manage.py`（人工调用即入口） |
| 装饰器/框架钩子 | `@router.*`、`@app.*`、`@fixture`、`@click.command`、`@field_validator` |
| Entry points | `pyproject.toml` / `setup.py` 的 `[project.scripts]`、`console_scripts` |

### 第二轮：框架与运行时核查

- FastAPI：路由注册依赖装饰器 + `_register_optional`（`main.py`），删除 router 文件前须查 `main.py` 的注册清单；
- Pydantic：`model_config`、`field_validator` 按名字绑定；
- pytest：`conftest.py` 的 fixture、`pytest.ini`/`pyproject.toml` 的 `testpaths`；
- 前端：`module.registry.ts` 侧效应注册、`index.html` 的 script 标签、`vite.config*.ts` 的 `rollupOptions.input`。

### 第三轮：跨仓库与运维核查

- **仓库外消费者**：`EMSXDataPipeline`（数据写入方）可能 import 本仓库 `data_access/*` 的常量/repository
  —— 删除 `data_access/` 下任何导出前必须在管道仓库确认；
- **运维接线**：`scripts/ops/*.ps1`、`scripts/deploy/*`（快捷方式/VBS/PS1）、Runbook、`relaunch_service.bat`；
- **部署配置**：Dockerfile、docker-compose、Nginx 配置中的命令与路径引用。

**任一轮命中 → 不删**。改为 `--suppress` 豁免并写明理由；若确属应长期保留的休眠接口，
写入 `scripts/cleanup/config.py` 的 `DEAD_FILE_EXEMPT` / `DEAD_SYMBOL_EXEMPT_NAMES`，让下一轮扫描不再重复报警。

---

## 三、行为保护网（无测试时的必做项）

```
无测试 → 先补特征测试（characterization test）→ 再动代码
```

1. **有测试**：记录基线（`pytest -q` 通过数），每批删除后复跑，比对数量不减少；
2. **无测试**：用「输入 → 输出对」录当前行为（哪怕是手工跑一次 CLI 保存输出），
   作为删除后的比对基线；不得因为「反正没人用」跳过这一步；
3. **性能改动**：同时记录基线耗时/内存数字（`time` / `tracemalloc`），优化后复测对比。

---

## 四、分批策略（收益/风险比降序）

| 批次 | 内容 | 风险 | 批间验证 |
|---|---|---|---|
| B1 | 临时/调试遗留（CL-07） | 极低 | 无需测试，扫一眼即可 |
| B2 | 空壳模块 + 不可达文件（CL-08/CL-01） | 低（需三轮质询） | 后端 `pytest` + 前端 `build` |
| B3 | 过时符号（CL-02） | 中 | 按模块分批，每批 `pytest` + `tsc -b` |
| B4 | 无用逻辑（CL-03~CL-06/CL-09） | 中（改的是活代码结构） | `pytest` 三套 + `vitest run` |
| B5 | 前端不可达文件（CL-10） | 中 | `npm run build:all-modules` + `vitest run` |

**批次纪律**：

- 一批一个提交，提交信息写明规则号与影响文件数（便于回退与审计）；
- **禁止跨批顺手改无关代码**（超范围加料是回退成本失控的主因）；
- 文档修订与删除**同一 commit**；历史记录（`specs/`、`plans/`、ADR、SQL 迁移注释）**不改**。

---

## 五、回退预案

- 删除前确认工作树干净（`git status`），保证 `git revert <sha>` 或 `git checkout <sha>~1 -- <path>` 可用；
- 不依赖 `_archive/` 目录保命（ADR-0014 的结论：归档目录仍会被全文检索命中、制造假引用，
  **git 历史才是正确的归档层**）；
- 数据库/数据文件**永不纳入回退范围**——它们本就不在代码树内，删除动作不得触碰。
- 清理分支命名遵循项目 Git 工作流：规格化任务分支名与 `specs/<feature-id>/` 一致
  （见 [`git-workflow.md`](../../../docs/spec/git-workflow.md)）。

---

## 六、禁止清单

- ❌ 未经用户明确授权就执行删除 / 改写；
- ❌ 删除未提交的工作树改动（先建议提交或 stash——**同一 worktree 内**）；
- ❌ 跨 worktree 操作其他任务的分支或文件；
- ❌ 以「代码看起来没用」为唯一理由删除（缺少三个质询之一的证据）；
- ❌ 把 `PF-xx` 候选当作性能缺陷直接重构；
- ❌ 在清理提交里混入功能改动（无法独立回退）。
