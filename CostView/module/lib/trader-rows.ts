/** 交易员复盘台行/详情键工具（纯函数，供列表选中态与详情取数共用）。 */

interface RowKeySource {
  order_id: string;
  order_as_of_date: string;
}

/**
 * 行唯一键：``OrderId`` 跨日可能重复（同一订单号在不同交易日是不同订单），
 * 故以「订单 + 日期」复合键作为选中态与详情取数的键。
 */
export const traderRowKey = (row: RowKeySource): string =>
  `${row.order_id}|${row.order_as_of_date}`;
