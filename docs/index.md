# EMSXView 文档规则

> L1 | 权威：文档分层与行数预算、写入时机、归档策略、校验命令、占位符与可配置参数约定 | 不权威：文档清单（见 `AGENTS.md` 文档地图）、项目现状与进度（见 `specs/057-execution-decision-loop/tasks.md`）

> **单一来源分工**：本文只管「文档怎么维护」；「该读哪份」在 [`AGENTS.md`](../AGENTS.md) 的文档地图，「现在到哪」在 `specs/057-execution-decision-loop/tasks.md` 的状态总览。三处互不复述。

---

## 1. 分层与行数预算

层数由判据算，不由文档数量抄：每份文档只属于一层，且必须被上一层指到。

| 层 | 回答什么 | 预算 | 谁读 | 落盘位置 |
|---|---|---|---|---|
| L0 | 我该看哪份？文档怎么改？ | ≤120 行 | 每次会话的 agent | 仓库根 `AGENTS.md` |
| L1 | 项目是什么、现在到哪、什么规矩 | 每份 ≤200 行 | 接手任务的人与 agent | `README.md`、`docs/index.md`、`specs/057-*/tasks.md` |
| L2 | 这个模块/机制为什么这样、怎么改它 | 无硬限，须被 L1 指到 | 要动该模块的人 | `docs/spec/`、`docs/api/`、`docs/ops/`、各模块 `README.md` |
| L3 | 当时怎么想、试过什么、证据在哪 | 不限，append-only | 追溯者与复核者 | `specs/`（在途计划）、`docs/archive/`、`docs/report-*.md` |

L0 超预算就下沉到 L1/L2，**不许缩句糊过去**——缩句只是把同样的上下文换个说法继续占坑。

## 2. 写入时机表

维护不是「记得更新文档」，而是每类改动都有指定动作。

| 事件 | 必改（按顺序） | 不用改 |
|---|---|---|
| 一批任务收尾 | `tasks.md` 该行状态 + 子编号/证据 + 日期 | `README.md`（结构没变时） |
| 新增/删除模块、依赖方向变 | `docs/spec/project-structure.md` 模块表 → `AGENTS.md` 地图 → 新 L2 | `QUICKSTART.md` |
| 做了取舍、否掉了方案 | 新 ADR → `docs/spec/memory.md` 的 ADR 索引（`audit_doc_drift.py` 会校验） → 相关 L1 加指针 | `tasks.md` 只记结果 |
| 对外用法变了 | `README.md` §9 | `docs/spec/` 细节 |
| 改了约定 | `docs/dev-guide.md` 或对应 `docs/spec/*`；若约束 agent 行为，加进 `AGENTS.md` 元规则 | L2 细节 |
| 文档结构变化 | **先** `AGENTS.md` 地图 → 再动文件 → 跑 `scripts/doc_check.py` | 其余 |
| 文档与代码冲突 | 描述性文档（现状/结构/进度）：改文档；规范性文档（约定/契约/安全）：改代码或记例外 | 不许两边各改一半 |
| 文档被取代 | 首部加「已被 <新文档> 取代」，移入 `docs/archive/` | 不许静默删除 |

**算做完的标志是 `python scripts/doc_check.py` 退出码 0**，不是「我改完了」。

## 3. 归档策略

满足任一条件即归档到 `docs/archive/YYYY-MM-DD/`：

- 主要描述的功能或阶段已经完成；
- 主要内容是一次性诊断、审计或修复报告；
- 仍在引用已删除或已迁移的路径；
- 已被新的真相源文档替代。

约定细则：

- 归档**保留原编号与目录名**：`docs/archive/YYYY-MM-DD/<feature-id>/`；活文档引用已归档计划时一律指向归档路径（2026-09-16、2026-09-21、2026-10-29 三批即此约定）。
- `specs/` 只承载在途计划；已完成计划归档后目录消失，新建计划时再建。
- 归档件首部必须留一行「归档于 YYYY-MM-DD；已被 <新文档> 取代」，禁止静默移动或删除。

### 例行体检（每 20 次提交或每月一次）

1. 对地图里每份文档跑 `git log -1 --format=%cs -- <路径>`：超过 180 天未改、且 `grep -rl <文件名>` 无引用 → 列候选归档，交用户确认后移入 `docs/archive/`。
2. `docs/report-*.md` 为一次性报告，**发布满 90 天**移入 `docs/archive/YYYY-MM-DD/`（截至 2026-10-29 尚未执行，为下一轮内容工作）。
3. 跑一次 `python scripts/doc_check.py --strict`，WARN 逐条判断是修还是记理由。

## 4. 文档校验

```bash
python scripts/doc_check.py            # 七项对账，退出码 0 = 通过（WARN 不计失败）
python scripts/doc_check.py --strict   # WARN 也算失败
python scripts/audit_doc_drift.py      # 契约级漂移（ADR 索引 / 模块边界 / 适配器表）
```

`doc_check.py` 只查能对账的部分：地图路径存在、`.md` 全量覆盖、被索引文档有元信息头、状态枚举与证据列、相对链接可解析、已失效术语未回流。它**不评价**「写得好不好」。

门禁位置（2026-10-29 定）：

- `audit_doc_drift.py`：`boundary.yml` 硬阻断 + `doc-drift-report.yml` 周报。
- `doc_check.py`：先接 `doc-drift-report.yml` 周报（非 strict、`continue-on-error`）；连续两周 0 FAIL 后再前移到 `boundary.yml`。
- 本地 git 钩子（`.githooks/`）**当前未启用**（`core.hooksPath` 仍指向 `.git/hooks`），本次决定暂不启用；因此质量门禁与文档对账目前只在 CI 与手动执行中生效。
- 检查 6/7 的范围已收窄：死链只查被地图覆盖且不在 `docs/archive/` 的文档，失效术语只查活文档（ADR 正文与归档件除外）。当前基线为 **0 FAIL / 0 WARN**，新出现的红灯都是真回归。

## 5. 占位符与可配置参数约定

文档（含 `README.md`、`QUICKSTART.md`、`AGENTS.md`、`docs/**`）中禁止写入与具体机器绑定的硬编码值，统一使用下列占位符。**本仓库内部文件一律以仓库相对路径引用**，确保文档自包含（不依赖仓库外路径或资源）。

### 5.1 路径占位

| 占位符 | 含义 | 说明 |
|---|---|---|
| `<repo-root>` | 仓库根 | 由仓库根 `.emsxview-root` marker 定位；脚本中用 `Find-EmsxviewRoot` 解析，禁止硬编码「向上 N 层」 |
| `${EMSXVIEW_DATA_DIR}` | 数据根 | 环境变量显式覆盖优先；默认值见 `data_access/config.py` 的 `Config.DEFAULT_DATA_DIR` |
| `<data-dir>` | 泛指某个数据目录 | 用于示例命令，实际取值即 `${EMSXVIEW_DATA_DIR}` |
| `<pipeline-repo>` | 独立数据管道仓库 EMSXDataPipeline 的本地检出路径 | **仓库外资源**：仅在说明归属时使用，文档中不得出现其具体磁盘路径 |

### 5.2 主机与端口占位

| 占位符 | 默认值 | 覆盖环境变量 |
|---|---|---|
| `<host>` | `localhost` | — |
| `<API_PORT>` / `<API_BASE_URL>` | `3000` / `http://<host>:3000` | `API_HOST`、`API_PORT` |
| `<MARKETVIEW_PORT>` / `<MARKETVIEW_BASE_URL>` | `8001` / `http://<host>:8001` | `MARKETVIEW_HOST`、`MARKETVIEW_PORT` |
| `<COSTVIEW_PORT>` / `<COSTVIEW_BASE_URL>` | `8002` / `http://<host>:8002` | `COSTVIEW_HOST`、`COSTVIEW_PORT` |
| `<FRONTEND_PORT>` | `5173`（开发态），容器态 `80` | `vite --port`、`VITE_API_URL`、`FRONTEND_PORT` |
| `<POSTGRES_PORT>` / `<PROMETHEUS_PORT>` / `<GRAFANA_PORT>` | `5432` / `9090` / `3001` | `backend/.env` 同名变量 |

### 5.3 仓库外引用处理原则

数据管道的 ETL 写入方已迁独立仓库 EMSXDataPipeline，本仓库仅保留只读访问层 `data_access/`：

- 文档需要指向「原 `DataPipeline/xxx` 文件」时，**改写为本仓库的对应路径**（`data_access/xxx`）；本仓库无对应物时只说明归属（「由独立仓库 EMSXDataPipeline 维护」），不写磁盘路径。
- 历史文档（`docs/archive/**`、`specs/**` 已归档计划）中的旧路径**保留原样作为历史记录**，但如出现用户目录等机器绑定路径，须替换为占位符。
