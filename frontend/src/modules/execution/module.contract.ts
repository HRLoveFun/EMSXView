/**
 * ExecutionView 模块对外接口契约 —— 模块 ↔ Shell 的唯一显式交互面。
 *
 * 职责边界：
 * - 输入（Shell → 模块）：`ExecutionModuleProps`，复用共享契约 `ModuleShellProps`，
 *   当前仅含 `onContribute` 上报通道。
 * - 输出（模块 → Shell）：`ExecutionModuleContribution`，工具栏所需的只读计数
 *   与 `refresh` / `clearCache` 两个受控动作。
 *
 * 约束：
 * - 模块外代码不得 import `@execution/*` 深层路径；跨模块交互一律经 `@shared/*` 契约层
 *   （`module-registry` 描述符 / `shell-context` 宿主服务 / `use-handoff-contracts` 交接合约）。
 * - 模块不得反向依赖 Shell 层（`@app/*`）——宿主能力只能通过 `@shared/lib/shell-context` 获取。
 * - 模块内部实现（hooks / services / stores / views）不属于对外契约，可自由重构。
 */
import type { ModuleContribution, ModuleShellProps } from '@shared/lib/module-registry';

/** 模块输入：Shell 注入的宿主能力（当前仅 `onContribute`）。 */
export type ExecutionModuleProps = ModuleShellProps;

/** 模块贡献的域计数：ExecutionView 固定上报订单数与路由数。 */
type ExecutionContributionCounts = {
  orders: number;
  routes: number;
};

/**
 * 模块输出：工具栏贡献信息。
 *
 * 以 Shell 的 `ModuleContribution` 为基准，仅把 `counts` 收窄为 ExecutionView 的固定计数键，
 * 保证 Shell 侧消费契约不因模块内部字段调整而漂移。
 */
export interface ExecutionModuleContribution extends Omit<ModuleContribution, 'counts'> {
  counts: ExecutionContributionCounts;
}
