# ADR-0012: 配置隔离 — DataPipeline/config 单一来源

> 状态: Accepted
> 日期: 2026-06-03
> 标签: data, configuration, refactoring

## 背景 (Context)

历史实现中数据库路径、表名散布在多个文件：
- `CostView/src/raw_fills_db.py` 写死 `'data/raw_fills.db'`
- `backend/api/config.py` 单独定义部分路径
- 各 router 局部硬编码表名

导致：
- 改路径需全局 grep
- 测试环境/生产环境切换需改多处
- DataPipeline 子域抽取后，配置职责不清晰

## 决策 (Decision)

**所有 DB 路径、表名、列定义统一从 `DataPipeline/config.py` 的 `Config` 类读取**：

- `Config.DB_PATHS['raw_fills']` / `Config.DB_PATHS['raw_bdib']` / ...
- `Config.TABLE_NAMES['fills']` / `Config.TABLE_NAMES['bdib_10s']` / ...
- `Config.COLUMNS[...]` 统一列定义
- `DataPipeline/config.py` 是**唯一**配置入口
- `platform_data/config_bridge.py` 仅做配置桥接（从 `Config` 派生 platform_data 所需视图）
- 业务代码**禁止**硬编码 `'*.db'` / 表名字面量

环境变量：
- `EMSXVIEW_DATA_DIR`：数据根目录。**默认已外置于项目外** `~\EMSXViewData\data`（见 [ADR-0016](0016-external-data-store-readonly-split.md)）；设此变量可显式覆盖（含指回旧布局 `CostView/data`）。

## 后果 (Conceptions)

### 正面
- 改路径/表名仅需改一处
- 测试/生产环境切换只需设环境变量
- 避免数据迁移时漏改

### 负面 / 取舍
- 新增表需要先在 `Config` 注册
- 业务代码 import `DataPipeline.config` 跨域

## 备选方案 (Considered Alternatives)

- 方案 A: 用环境变量分散管理
  - 否决原因: 类型不安全；IDE 补全失效
- 方案 B: 用配置中心（Consul/etcd）
  - 否决原因: 引入额外基础设施；当前规模不匹配
- 方案 C: 保持散落配置
  - 否决原因: 已被数据迁移事故反复证明不可持续

## 相关 ADR

- 引用: [ADR-0005](0005-data-pipeline-extraction.md)
- 被引用: 无

## 实施注意事项

- 配套反模式: `AP-04 数据库路径硬编码`（见 `docs/spec/anti-patterns.md`）
- 配套测试: `tests/boundaries/test_db_path_from_config.py`
