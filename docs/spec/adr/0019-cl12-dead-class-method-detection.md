# ADR-0019: CL-12 类方法零引用检测 — 词边界匹配 + 同名实体区分

> 状态: Accepted
> 日期: 2026-09-15
> 标签: refactoring, cleanup, tooling, scripts

## 背景 (Context)

ADR-0017 建立 CL-xx 清理规则集时，明确记录了一项能力边界：

> CL-02 刻意不判类方法，类方法死代码需依赖 vulture（外部工具，可选）。

该缺口在两轮清理中反复付出成本 —— 真死方法只能靠人工阅读发现，或依赖未安装的外部工具：

- `SqliteFillReadRepository.get_all_processed_fills()`（2026-09-10）与
  `TcaQueryService` 的 4 个 `_*_conn` helper（2026-09-15）均由人工阅读发现；
- `data_access/storage/market_store.py` 的 `get_market_context`（44 行）连同 5 个仅供其调用的
  helper 构成**整条死链**（约 110 行），模块级规则完全不可见。

实现过程还暴露了两类**静态判定自身的陷阱**（均由真实漏报反推，非理论推演）：

| 陷阱 | 现象 | 后果 |
|---|---|---|
| 子串遮蔽 | 以 `name in text` 判定「出现」：`get_distinct_dates` 被 `get_distinct_dates_in_range` 遮蔽；`get_processed_dates` 被 `get_unprocessed_dates` 遮蔽 | 真死方法被判存活（假阴性） |
| 同名实体混淆 | `TcaQueryService._fill_bdib_conn` 被 `tca_query_builder.py` 的同名**模块级函数**遮蔽；`update_parent_filled` 被测试替身的同名方法遮蔽 | 同上 |

## 决策 (Decision)

1. **新增 `CL-12` 过时类方法（零引用）**，实现于 `scripts/cleanup/detectors/dead_methods.py`，
   注册进 `CL_DETECTORS`；阈值与豁免的唯一真相源仍为 `scripts/cleanup/config.py`。
2. **判定口径**：方法名在全库语料（`.py` + 前端 `.ts/.tsx`，排除 `docs/`·`specs/`·`plans/`）中的出现，
   若既不是同名符号的定义/导入，也不归属该文件自有的同名模块级符号，则计为引用。
   - **词边界匹配**：`(?<![\w.])name(?![\w])`。`_` 属 `\w`，故 `get_x` 不被 `get_x_y` 遮蔽；
   - **同名实体区分**：文件自带同名模块级符号（def / class / 赋值 / import）时，
     其内**裸标识符**出现归属该自有符号，仅 `obj.name` 属性访问形态计为引用；
   - 其余一切出现（注释、字符串、`getattr(obj, "name")`）一律计为引用 ——
     **漏报可接受、误删不可接受**（与 CL-02 同一取向）。
3. **豁免**（任一命中即不报）：dunder；框架装饰器（fixture / property / route / ...）；
   docstring 显式声明为占位或兼容 no-op；桩代码目录与测试目录；
   框架/多态基类（Protocol / ABC / BaseModel / Enum / TestCase / NodeVisitor ...）；
   类体内含动态名字访问（getattr / vars / locals / eval / ...）或代理 dunder。
4. **人工豁免清单 `DEAD_METHOD_EXEMPT_NAMES`**：「契约声明的对外 API」零静态调用方 ≠ 可删。
   首批收口 handoff 适配器的 `clear_market_to_execution` / `clear_cost_to_execution`，
   依据 `.codebuddy/rules/module-boundary.md` §2.3 的「外部可见方法」列表。

## 后果 (Consequences)

### 正面

- 补齐 ADR-0017 记录的能力边界，类方法死代码不再依赖外部工具（纯标准库，零第三方依赖，永远可用）；
- 首次全库运行产出 14 项候选，经三轮质询后删除 10 项（约 130 行）；
  其中 `ConnectionManager.get_admin_connection` 属写/管理能力，删除进一步收窄 ADR-0016 的只读边界；
- **两次真实漏报固化为回归测试**：`get_x` 与 `get_x_y` 的子串关系、
  模块级同名函数与类方法的实体归属，各有独立用例（`TestDeadMethods`）。

### 负面 / 取舍

- 无法证明「同名属性访问来自本类实例」，`obj.name()` 一律计为引用 → 存在漏报；
- 词元级判定不区分「注释提及」与「真实调用」，注释里的符号名会掩盖死代码；
- 类方法若被运行时注入（DI 容器按名解析）则静态不可证伪，依赖 `--suppress` 收口。

## 备选方案 (Considered Alternatives)

- 方案 A: 引入 vulture 作为门禁依赖
  - 否决原因: 与 ADR-0017「不新建第二套门禁框架、零第三方依赖」冲突；
    外部工具仍留在 skill 的可选增强位（见 `references/tool-matrix.md`）。
- 方案 B: 构建属性访问图并做类型推断（判定同名属性是否来自本类）
  - 否决原因: 需 mypy / pyright 级别类型推断，超出清理门禁的启发式定位与 25s 增量预算。

## 相关 ADR

- 扩展: [ADR-0017](0017-cleanup-and-perf-hotspot-mechanism.md)（CL-xx 规则集与门禁基础设施）
- 关联: [ADR-0014](0014-dead-code-cleanup.md)（死代码清理实践与「宁漏报不误删」原则）
- 关联: [ADR-0016](0016-external-data-store-readonly-split.md)（只读边界——`get_admin_connection` 删除依据）

## 实施注意事项

- 分支: `chore/cleanup-entropy-2026-09-15`
- 门禁基线: `pytest backend CostView scripts/quality_gate/tests scripts/cleanup/tests`
  → 464 passed / 1 skipped；`tsc -b` exit 0；`vitest run` 19 文件 / 155 用例
- 检测器自测: `scripts/cleanup/tests/test_cleanup.py::TestDeadMethods`（12 用例，含 2 条回归）
- 收口口径: 引入后首轮 `cleanup --ruleset cl` 报 14 项候选 → 删除 10 项 + 契约豁免 4 项 → 归零
