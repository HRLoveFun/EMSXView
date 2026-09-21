import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { EvaluationReport } from '../../types';

/** 报告内嵌评估摘要（027）。
 *
 *  与独立「Evaluation」视图**消费同一份 payload**（后端同一编排函数），因此两者
 *  不可能出现口径分叉；此处只渲染摘要，完整分组与检验明细见该视图。
 *  评估未启用或无数据时返回 ``null``（不占位、不误导）。
 */
export function EvaluationSummary({
  evaluation,
}: {
  evaluation?: EvaluationReport | null;
}) {
  if (!evaluation?.enabled) {
    return null;
  }
  const blocks = evaluation.sections?.dimensions ?? [];
  if (!blocks.length) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">算法执行质量综合评估</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 overflow-x-auto">
        <p className="text-xs text-muted-foreground">
          主基准 {evaluation.primary_benchmark}；组间比较在控制维度（市场 / 时段 / 流动性 /
          波动率）的共同层内进行并按层样本量加权合并，层覆盖率与置信度随行披露 ——
          完整明细见「Evaluation」视图。
        </p>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="px-2 py-1">比较维度</th>
              <th className="px-2 py-1 text-right">分组数</th>
              <th className="px-2 py-1">相对其余最优</th>
              <th className="px-2 py-1">相对其余最差</th>
              <th className="px-2 py-1">置信度</th>
              <th className="px-2 py-1 text-right">可检测效应</th>
            </tr>
          </thead>
          <tbody>
            {blocks.map((block) => {
              const confidence = Array.from(
                new Set(block.rows.map((row) => row.vs_others.confidence)),
              ).join(' / ');
              const mde = block.highlights.minimum_detectable_effect;
              return (
                <tr key={block.dimension} className="border-b border-border/60">
                  <td className="px-2 py-1">{block.dimension}</td>
                  <td className="px-2 py-1 text-right font-mono">{block.group_count}</td>
                  <td className="px-2 py-1">{block.highlights.best?.label ?? '—'}</td>
                  <td className="px-2 py-1">{block.highlights.worst?.label ?? '—'}</td>
                  <td className="px-2 py-1">{confidence || '—'}</td>
                  <td className="px-2 py-1 text-right font-mono">
                    {mde == null ? '—' : mde.toFixed(2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
