import type {
  CostViewConfig,
  ExportFormat,
  ExportScope,
  TcaReport,
  TcaRouteSummary,
} from '../types';

interface ExportParams {
  format: ExportFormat;
  scope: ExportScope;
  report: TcaReport;
  config: CostViewConfig;
  selectedOrder: TcaRouteSummary | null;
}

interface FlatRouteRow {
  [key: string]: string | number | boolean | null;
  orderId: string;
  routeId: string;
  date: string;
  exchange: string | null;
  account: string | null;
  symbol: string;
  currency: string | null;
  side: string;
  type: string | null;
  amount: number | null;
  routeShares: number | null;
  limitPrice: number | null;
  stopPrice: number | null;
  broker: string;
  strategyType: string | null;
  algo: string;
  traderName: string | null;
  fill: number | null;
  fillContinuous: number | null;
  fillClose: number | null;
  parRate: number | null;
  parRateContinuous: number | null;
  parRateClose: number | null;
  pAvg: number | null;
  pAvgContinuous: number | null;
  pnlVwap: number | null;
  pnlVwapContinuous: number | null;
  rpm: number | null;
  rpmContinuous: number | null;
  pwp5: number | string | null;
  pwp10: number | string | null;
  pwp15: number | string | null;
  pwp20: number | string | null;
  pwp25: number | string | null;
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

function flattenRoute(route: TcaRouteSummary): FlatRouteRow {
  return {
    orderId: route.order_id,
    routeId: route.route_id,
    date: route.order_as_of_date,
    exchange: route.exchange,
    account: route.account,
    symbol: route.equ_ticker ?? '',
    currency: route.currency,
    side: route.side ?? '',
    type: route.type,
    amount: route.amount,
    routeShares: route.route_shares,
    limitPrice: route.limit_price,
    stopPrice: route.stop_price,
    broker: route.broker ?? '',
    strategyType: route.strategy_type,
    algo: route.algo ?? '',
    traderName: route.trader_name,
    fill: route.fill,
    fillContinuous: route.fill_continuous,
    fillClose: route.fill_close,
    parRate: route.par_rate,
    parRateContinuous: route.par_rate_continuous,
    parRateClose: route.par_rate_close,
    pAvg: route.p_avg,
    pAvgContinuous: route.p_avg_continuous,
    pnlVwap: route.pnl_vwap,
    pnlVwapContinuous: route.pnl_vwap_continuous,
    rpm: route.rpm,
    rpmContinuous: route.rpm_continuous,
    pwp5: route.pwp_5,
    pwp10: route.pwp_10,
    pwp15: route.pwp_15,
    pwp20: route.pwp_20,
    pwp25: route.pwp_25,
  };
}

function buildRouteRows(report: TcaReport): FlatRouteRow[] {
  return report.orders.map(flattenRoute);
}

function buildSummaryRows(report: TcaReport, config: CostViewConfig): Array<Record<string, unknown>> {
  return [
    {
      generatedAt: report.generated_at,
      totalRoutes: report.total_orders,
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
  const rows = params.scope === 'selected-order' && params.selectedOrder
    ? [flattenRoute(params.selectedOrder)]
    : buildRouteRows(params.report);
  const csv = rowsToCsv(rows);
  const fileName = `costview-${params.scope}-${new Date().toISOString().slice(0, 10)}.csv`;
  downloadBlob(new Blob([csv], { type: 'text/csv;charset=utf-8' }), fileName);
}

async function exportExcel(params: ExportParams): Promise<void> {
  const routeRows = params.scope === 'selected-order' && params.selectedOrder
    ? [flattenRoute(params.selectedOrder)]
    : buildRouteRows(params.report);

  const sheets: Array<{ name: string; rows: Array<Record<string, unknown>> }> = [
    { name: 'Summary', rows: buildSummaryRows(params.report, params.config) },
    { name: 'Routes', rows: routeRows },
    { name: 'Thresholds', rows: buildThresholdRows(params.config) },
  ];

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

  const selectedRouteHtml = params.selectedOrder
    ? `
      <section>
        <h2>Selected Route</h2>
        ${renderRowsAsHtml([flattenRoute(params.selectedOrder)])}
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
          <h2>Routes</h2>
          ${renderRowsAsHtml(buildRouteRows(params.report))}
        </section>
        ${selectedRouteHtml}
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
    throw new Error('Select a route before exporting selected-route detail.');
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
