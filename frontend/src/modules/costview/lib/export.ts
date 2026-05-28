import type {
  CostViewConfig,
  ExportFormat,
  ExportScope,
  TcaOrderSummary,
  TcaReport,
  TcaRouteDetail,
} from '../types';

interface ExportParams {
  format: ExportFormat;
  scope: ExportScope;
  report: TcaReport;
  config: CostViewConfig;
  selectedOrder: TcaOrderSummary | null;
}

interface FlatOrderRow {
  [key: string]: string | number | boolean | null;
  orderId: string;
  date: string;
  symbol: string;
  side: string;
  algo: string;
  fillPct: number | null;
  execPrice: number | null;
  benchmarkVwap: number | null;
  trackingErrorBps: number | null;
  volumePctInterval: number | null;
  volumePctAdv20: number | null;
  intradayVolatility: number | null;
  priceMovementPct: number | null;
  dataQualityWarning: boolean;
}

interface FlatRouteRow {
  [key: string]: string | number | boolean | null;
  orderId: string;
  routeId: string;
  date: string;
  broker: string;
  side: string;
  startTime: string;
  endTime: string;
  fillPct: number | null;
  execPrice: number | null;
  benchmarkVwap: number | null;
  trackingErrorBps: number | null;
  volumePctInterval: number | null;
}

function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function csvEscape(value: string | number | boolean | null | undefined): string {
  if (value == null) return '';
  const text = String(value);
  if (/[",\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function xmlEscape(value: string | number | boolean | null | undefined): string {
  if (value == null) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function rowsToCsv<T extends Record<string, unknown>>(rows: T[]): string {
  if (!rows.length) return '';
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(',')];

  for (const row of rows) {
    lines.push(headers.map((header) => csvEscape(row[header] as string | number | boolean | null | undefined)).join(','));
  }

  return lines.join('\n');
}

function flattenOrder(order: TcaOrderSummary): FlatOrderRow {
  return {
    orderId: order.order_id,
    date: order.order_as_of_date,
    symbol: order.equ_ticker ?? '',
    side: order.side ?? '',
    algo: order.algo ?? '',
    fillPct: order.fill_pct,
    execPrice: order.exec_price,
    benchmarkVwap: order.interval_vwap,
    trackingErrorBps: order.tracking_error_bps,
    volumePctInterval: order.volume_pct_interval,
    volumePctAdv20: order.volume_pct_adv20,
    intradayVolatility: order.intraday_volatility,
    priceMovementPct: order.price_movement_pct,
    dataQualityWarning: order.data_quality_warning,
  };
}

function flattenRoute(order: TcaOrderSummary, route: TcaRouteDetail): FlatRouteRow {
  return {
    orderId: order.order_id,
    routeId: route.route_id,
    date: order.order_as_of_date,
    broker: route.broker ?? '',
    side: route.side ?? '',
    startTime: route.start_time ?? '',
    endTime: route.end_time ?? '',
    fillPct: route.fill_pct,
    execPrice: route.exec_price,
    benchmarkVwap: route.interval_vwap,
    trackingErrorBps: route.tracking_error_bps,
    volumePctInterval: route.volume_pct_interval,
  };
}

function buildOrdersRows(report: TcaReport): FlatOrderRow[] {
  return report.orders.map(flattenOrder);
}

function buildRouteRows(report: TcaReport): FlatRouteRow[] {
  return report.orders.flatMap((order) => order.routes.map((route) => flattenRoute(order, route)));
}

function buildSummaryRows(report: TcaReport, config: CostViewConfig): Array<Record<string, unknown>> {
  return [
    {
      generatedAt: report.generated_at,
      totalOrders: report.total_orders,
      filters: JSON.stringify(report.filters),
      exportFormatDefault: config.exportDefaults.format,
      exportScopeDefault: config.exportDefaults.scope,
    },
  ];
}

function buildThresholdRows(config: CostViewConfig): Array<Record<string, unknown>> {
  return Object.values(config.rules).map((rule) => ({
    key: rule.key,
    label: rule.label,
    mode: rule.mode,
    warningThreshold: rule.warningThreshold,
    criticalThreshold: rule.criticalThreshold,
    enabled: rule.enabled,
    unit: rule.unit,
    description: rule.description,
  }));
}

async function exportCsv(params: ExportParams): Promise<void> {
  const rows: Array<Record<string, unknown>> = params.scope === 'selected-order' && params.selectedOrder
    ? params.selectedOrder.routes.map((route) => flattenRoute(params.selectedOrder as TcaOrderSummary, route))
    : buildOrdersRows(params.report);
  const csv = rowsToCsv(rows);
  const fileName = `costview-${params.scope}-${new Date().toISOString().slice(0, 10)}.csv`;
  downloadBlob(new Blob([csv], { type: 'text/csv;charset=utf-8' }), fileName);
}

async function exportExcel(params: ExportParams): Promise<void> {
  const routeRows = params.scope === 'selected-order' && params.selectedOrder
    ? params.selectedOrder.routes.map((route) => flattenRoute(params.selectedOrder as TcaOrderSummary, route))
    : buildRouteRows(params.report);

  const sheets: Array<{ name: string; rows: Array<Record<string, unknown>> }> = [
    { name: 'Summary', rows: buildSummaryRows(params.report, params.config) },
    { name: 'Orders', rows: buildOrdersRows(params.report) },
    { name: 'Thresholds', rows: buildThresholdRows(params.config) },
  ];

  if (routeRows.length) {
    sheets.splice(2, 0, { name: 'Routes', rows: routeRows });
  }

  const workbookXml = `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:html="http://www.w3.org/TR/REC-html40">
${sheets.map((sheet) => {
  const headers = sheet.rows.length ? Object.keys(sheet.rows[0]) : ['empty'];
  const headerRow = `<Row>${headers.map((header) => `<Cell><Data ss:Type="String">${xmlEscape(header)}</Data></Cell>`).join('')}</Row>`;
  const bodyRows = sheet.rows.length
    ? sheet.rows.map((row) => `<Row>${headers.map((header) => {
        const value = row[header] as string | number | boolean | null | undefined;
        const type = typeof value === 'number' ? 'Number' : typeof value === 'boolean' ? 'String' : 'String';
        const formatted = typeof value === 'boolean' ? String(value) : value;
        return `<Cell><Data ss:Type="${type}">${xmlEscape(formatted)}</Data></Cell>`;
      }).join('')}</Row>`).join('')
    : '<Row><Cell><Data ss:Type="String">No rows available</Data></Cell></Row>';
  return `<Worksheet ss:Name="${xmlEscape(sheet.name)}"><Table>${headerRow}${bodyRows}</Table></Worksheet>`;
}).join('')}
</Workbook>`;

  const fileName = `costview-${params.scope}-${new Date().toISOString().slice(0, 10)}.xls`;
  downloadBlob(new Blob([workbookXml], { type: 'application/vnd.ms-excel;charset=utf-8' }), fileName);
}

function renderRowsAsHtml(rows: Array<Record<string, unknown>>): string {
  if (!rows.length) {
    return '<p>No rows available.</p>';
  }

  const headers = Object.keys(rows[0]);
  const headerHtml = headers.map((header) => `<th>${header}</th>`).join('');
  const bodyHtml = rows.map((row) => {
    const cells = headers.map((header) => `<td>${String(row[header] ?? '')}</td>`).join('');
    return `<tr>${cells}</tr>`;
  }).join('');

  return `<table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table>`;
}

async function exportPdf(params: ExportParams): Promise<void> {
  const popup = window.open('', '_blank', 'noopener,noreferrer,width=1200,height=900');
  if (!popup) {
    throw new Error('Popup blocked while opening PDF print preview.');
  }

  const selectedOrderHtml = params.selectedOrder
    ? `
      <section>
        <h2>Selected Order</h2>
        ${renderRowsAsHtml([flattenOrder(params.selectedOrder)])}
        <h3>Routes</h3>
        ${renderRowsAsHtml(params.selectedOrder.routes.map((route) => flattenRoute(params.selectedOrder as TcaOrderSummary, route)))}
      </section>
    `
    : '';

  const html = `
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>CostView Report</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 24px; color: #111827; }
          h1, h2, h3 { margin: 0 0 12px; }
          section { margin-bottom: 24px; }
          table { border-collapse: collapse; width: 100%; margin-top: 12px; }
          th, td { border: 1px solid #d1d5db; padding: 6px 8px; font-size: 12px; text-align: left; }
          th { background: #f3f4f6; }
          .meta { color: #4b5563; font-size: 12px; margin-bottom: 16px; }
        </style>
      </head>
      <body>
        <h1>CostView Analysis Report</h1>
        <div class="meta">Generated ${new Date().toLocaleString()} · Scope: ${params.scope}</div>
        <section>
          <h2>Summary</h2>
          ${renderRowsAsHtml(buildSummaryRows(params.report, params.config))}
        </section>
        <section>
          <h2>Orders</h2>
          ${renderRowsAsHtml(buildOrdersRows(params.report))}
        </section>
        ${selectedOrderHtml}
        <section>
          <h2>Thresholds</h2>
          ${renderRowsAsHtml(buildThresholdRows(params.config))}
        </section>
      </body>
    </html>
  `;

  popup.document.open();
  popup.document.write(html);
  popup.document.close();
  popup.focus();
  popup.print();
}

export async function exportCostViewReport(params: ExportParams): Promise<void> {
  if (params.scope === 'selected-order' && !params.selectedOrder) {
    throw new Error('Select an order before exporting selected-order detail.');
  }

  switch (params.format) {
    case 'csv':
      await exportCsv(params);
      return;
    case 'excel':
      await exportExcel(params);
      return;
    case 'pdf':
      await exportPdf(params);
      return;
    default:
      throw new Error('Unsupported export format.');
  }
}