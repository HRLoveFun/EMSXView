/** Pnl VWAP 跨页面统一命名与 tooltip（唯一来源，禁止各页面各写一套）。 */

export const PNL_VWAP_LABELS = {
  routeMean: '平均 Pnl VWAP（路由未加权）',
  routeMeanPage: '平均 Pnl VWAP（当前页，路由未加权）',
  routeMeanAbs: '平均 |Pnl VWAP|',
  turnoverWeighted: 'Pnl VWAP（成交额加权）',
  sharesOrder: 'Pnl VWAP（股数加权，订单级）',
  turnoverOrder: 'Pnl VWAP（订单成交额加权）',
  continuousBps: '平均连续 Pnl VWAP (bps)',
} as const;

export const PNL_VWAP_SIGN_NOTE =
  'pnl_vwap 为上游原始带符号值；严重度按 |pnl_vwap| 判定，正负方向以数据字典为准。';

export const PNL_VWAP_TOOLTIPS = {
  routeMean:
    `当前加载结果集中所有 pnl_vwap 非空路由的算术平均，不做成交额加权；小单与大单同权。样本为当前结果集，与 Report 的成交额加权值不可直接比较。${PNL_VWAP_SIGN_NOTE}`,
  routeMeanPage:
    `当前页路由的算术平均，翻页或修改 Max Orders 会改变结果。${PNL_VWAP_SIGN_NOTE}`,
  routeMeanAbs:
    `cohort 内路由 |pnl_vwap| 的算术平均，衡量成本绝对幅度、不含方向；与带符号均值、成交额加权均值均不同。`,
  turnoverWeighted:
    `按 fill × p_avg 成交额加权；小单影响被稀释。附样本覆盖与权重覆盖，覆盖不足时结论仅供参考。${PNL_VWAP_SIGN_NOTE}`,
  sharesOrder:
    `订单内按成交股数 fill 加权，是订单级指标；跨订单比较时应再按成交额加权，不能对订单值做简单平均。${PNL_VWAP_SIGN_NOTE}`,
  turnoverOrder:
    `先算订单的 pnl_vwap，再按订单成交额 fill × p_avg 加权汇总；与路由层加权可能因订单内路由结构不同而略有差异。${PNL_VWAP_SIGN_NOTE}`,
  continuousBps:
    '连续时段 pnl_vwap_continuous 的均值（bps）；不是波动率，也不是 pnl_vwap。',
} as const;
