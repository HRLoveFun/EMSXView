# 集成指南（Integration Guide）

本 skill 的脚本**开箱可用**，无需集成即可运行：

```bash
python scripts/cleanup.py --report
```

以下为按需加深的四级集成，**建议按 L1 → L4 顺序逐级推进**，每级都先建基线再谈门禁
（对齐 `docs/spec/quality-gate.md` 的 guard 门禁演进思想：新增阻断 / 存量放行）。

---

## L0 直接使用（默认，零改动）

| 场景 | 命令 |
|---|---|
| 全库清理 + 性能盘点 | `python scripts/cleanup.py --report` |
| 只看清理侧 | `python scripts/cleanup.py --ruleset cl --json` |
| 只看性能侧 | `python scripts/cleanup.py --ruleset pf --report` |
| 误报豁免 | `python scripts/cleanup.py --suppress <fingerprint> --note "理由"` |
| 检测器自测 | `python -m pytest scripts/cleanup/tests/ -q` |

产出：`scripts/reports/cleanup/cleanup.db`（基线趋势库）+ `report-YYYYMMDD.md`。

---

## L1 与 `quality_gate` 统一（推荐）

`cleanup` 复用 `quality_gate` 的 `Finding` / `RuleSet` / `ScanResult` / `GateStore` / `scoring`，
所有 finding 的 `ruleset` 为 `oe`，因此**可以直接注册为 quality_gate 检测器**，无需转换层。

### 步骤

1. 在 `scripts/quality_gate/detectors/__init__.py` 导入清理检测器并追加到全量列表
   （**只加到 `FULL_DETECTORS`，不要加到 `STAGED_DETECTORS`** —— 清理检测需全库索引，
   且 pre-commit 不应被启发式规则拖慢）：

```python
from scripts.cleanup.detectors import dead_files, dead_logic, dead_symbols, perf

FULL_DETECTORS: list[Detector] = [
    ap_adapter.detect,
    complexity.detect,
    duplication.detect,
    over_abstraction.detect,
    needless_patterns.detect,
    dead_modules.detect,
    frontend_light.detect,
    dead_files.detect,       # CL-01 / CL-07 / CL-08
    dead_symbols.detect,     # CL-02
    dead_logic.detect,       # CL-03 ~ CL-06 / CL-09
    perf.detect,             # PF-01 ~ PF-06
]
```

2. **先建基线再考虑门禁**。注册后第一次 `python scripts/quality_gate.py` 会把清理 finding
   全部记为 `open` 并按 `oe_new` 语义阻断——这是 guard 模式的设计行为，不是 bug。
   正确做法：

```bash
python scripts/quality_gate.py                      # 建基线（会阻断一次，属预期）
python scripts/quality_gate.py --ruleset oe         # 确认存量已放行
```

3. 若希望清理与门禁**保持独立基线**（推荐：删除决策节奏慢于代码提交），
   则**不要注册**，让 `cleanup` 使用自己的 `scripts/reports/cleanup/cleanup.db`，
   在报告中同时引用 `quality_gate` 的结果（两套规则取并集）：

```bash
python scripts/quality_gate.py --ruleset oe --report
python scripts/cleanup.py --report
```

> 取舍：注册 = 统一技术债视图与趋势，但清理噪声会进入提交门禁；
> 不注册 = 关注点分离，但需要人工合并两份报告。**默认建议不注册**（本仓库当前采用此方案）。

---

## L2 pre-commit 增量集成

`.githooks/pre-commit` 已有 `quality_gate.py --staged` 调用。追加清理增量快检
（**必须 fail-open + 有限时预算**，否则会拖慢每一次提交）：

```bash
git diff --cached --name-only | grep -E '\.(py|ts|tsx)$' \
  | python scripts/cleanup.py --staged --quiet || true
```

要点：

- `--staged` 只判定暂存文件，但**全库索引照常构建**（`ScanContext.all_*`），因此不会因图不完整而误报；
- 检测器异常一律 fail-open（`cli._run_detectors`），监测器故障不得阻断开发；
- 默认退出码 0；只有加 `--strict` 才在新增项时返回 1。**pre-commit 阶段建议不加 `--strict`**。

---

## L3 CI 强门禁（团队决策后启用）

```yaml
# 示意（按实际 CI 平台调整）
- name: cleanup gate
  run: |
    python scripts/cleanup.py --strict --report
    python scripts/quality_gate.py --staged --quiet
```

启用前提：

1. 已完成一轮全量扫描；
2. 历史误报已 `--suppress` 收口（`suppressed` 不计入 `new`）；
3. 团队接受「静态候选即阻断」的误报成本。

否则会陷入「每次提交都被启发式规则拦住」的循环——这正是 `quality_gate` 采用 guard 模式的原因。

---

## L4 规则集与文档沉淀

| 动作 | 位置 |
|---|---|
| 新增/调整清理规则 | `scripts/cleanup/detectors/*.py` + `scripts/cleanup/config.py` + 本 skill `references/ruleset-cl.md` |
| 新增/调整性能规则 | `scripts/cleanup/detectors/perf.py` + `references/ruleset-pf.md` |
| 阈值调优 | **只改** `scripts/cleanup/config.py`（唯一真相源），不得散落到检测器 |
| 与反模式清单互引 | 在 `docs/spec/anti-patterns.md` 顶部索引补一句「清理/性能规则见 `.codebuddy/skills/code-cleanup/references/`」 |
| 决策记录 | 新增 ADR（编号 `docs/spec/adr/README.md` 的「流程、文档、测试规范」段为 `0700-0799`，编号全局递增、永不复用） |
| 架构记忆 | `docs/spec/memory.md` 的 ADR 索引表补一行 |
| 检测器自测 | `scripts/cleanup/tests/test_cleanup.py` —— 每条新规则须同时有「命中」与「不误报」两侧用例 |

---

## 与既有基础设施的复用边界（避免重复建设）

| 已存在 | 本 skill 的做法 |
|---|---|
| `scripts/quality_gate/ast_utils.py` | **直接导入复用**（复杂度、嵌套、指纹、根定位），不另写一份 |
| `scripts/quality_gate/models.py` | 复用 `Finding` / `RuleSet` / `Severity`，不定义平行模型 |
| `scripts/quality_gate/store.py` | 复用 `GateStore` 基线机制，仅换 DB 路径，实现「同基础设施、独立基线」 |
| `scripts/quality_gate/detectors/dead_modules.py` | CL-01 **包装**其算法（不重写），只扩扫描范围与规则编号 |
| `scripts/quality_gate/config.py` | 复用 `PYTHON_SCAN_ROOTS` 之外的排除清单与 `FRONTEND_ALIASES`（别名漂移需同步） |
| `/cleanup-tmp` 命令 | 管仓库根 `_tmp/`；CL-07 管业务树内残留，两者互补不重叠 |

**自反性约束**（对齐 `docs/spec/quality-gate.md`）：监测机制本身不得成为过度工程 ——
零第三方依赖、检测器共享工具、单文件保持精简、不为统一而重写既有实现。
