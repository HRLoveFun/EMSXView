# ADR-0011: FX 汇率处理规则

> 状态: Accepted
> 日期: 2026-06-03
> 标签: data-processing, frontend

## 背景 (Context)

FX 报价存在两种形式：
- **direct quote**：USD/JPY = 150.50（1 USD = 150.50 JPY）
- **inverse quote**：USD/JPY inverse = 0.00664（1 JPY = 0.00664 USD）

市场实践中：
- 主流报价方提供 direct
- 部分货币（GBP、EUR、AUD、NZD）传统上用 inverse
- 报价方可能采用 10x/100x/1000x 缩放（例如 JPY pair 用 100x = 15050）

历史实现把 direct/inverse 不一致直接报 WARNING，导致大量噪声告警。

## 决策 (Decision)

FX 汇率处理规则（按优先级）：

1. **direct 与 inverse 同时存在时，inverse 更可靠**（交易所惯例）
2. **已知 10x/100x/1000x 缩放报价视为报价约定**，不产生 WARNING
3. **只有缩放归一化后仍显著偏离**（> 阈值）的 direct/inverse 差异才保留 WARNING
4. 缩放归一化后正常范围内的差异 → INFO 或静默

实现位置：FX 处理集中在 `DataPipeline/src/processing/fx_normalizer.py`（或对应模块）。

## 后果 (Consequences)

### 正面
- 日志噪声显著降低
- inverse 优先避免英/欧/澳/纽币种错算
- 真实异常仍能浮出

### 负面 / 取舍
- 阈值需要定期回顾
- 缩放约定变化时需更新配置

## 备选方案 (Considered Alternatives)

- 方案 A: 全部按 direct 处理
  - 否决原因: 4 种主流货币会错
- 方案 B: 关闭所有 FX 差异告警
  - 否决原因: 失去异常发现能力
- 方案 C: 引入外部 FX provider（Bloomberg FXGO）
  - 否决原因: 当前 EMSX 报价已含 FX 字段，外部依赖成本不划算

## 相关 ADR

- 引用: 无
- 被引用: 无
