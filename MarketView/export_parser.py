"""EMSX 订单导出解析与 PM Note 意图映射（057 DL-01，只读 MVP）。

只读收件箱中最新一份手工导出 CSV，产出盘前单 v0（PreTradeOrderBoard）。
不落库、不碰 Bloomberg、不碰下单路径；收件箱目录在仓库外（config 配置）。

解析规则金标准：specs/057-execution-decision-loop/plan.md 附录 A 脱敏样例。
DL-07 管道侧入库（blotter_snapshots / order_intent）后，MarketView 改读表、
删除本直读路径——在那之前本模块是意图的唯一来源。
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from platform_data.contracts.order_intent_contracts import (
    INTENT_MAPPING_VERSION,
    INTENT_SOURCE_EMSX_EXPORT,
    BlotterOrderRow,
    OrderIntent,
    PreTradeOrderBoard,
    UnmatchedOrder,
)

# ── 解析常量 ───────────────────────────────────────────────────────────────────

# 缺以下任一列即整份报错（连接键与订单要素，错列比缺列更危险）
REQUIRED_COLUMNS = (
    "PM Note 13",
    "Code",
    "Exch Code",
    "Side",
    "Qty",
    "Status",
    "Create Time (As of)",
)

# Bloomberg 数据导出受限标记：受限列整体按可选处理
RESTRICTED_MARKER = "Data Export Restricted"
# 脱敏/遮蔽值：按缺失处理（附录 A 样例中 `***` 为数值遮蔽、MASKED 为整列遮蔽）
_MASKED_VALUES = {"***", "MASKED"}

# PM Note 前缀 → 意图：「数字 % @Close」取收盘比例；Spec.Instr. 为特殊指令
_CLOSE_PCT_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%\s*@Close\s*$")
_SPECIAL_PREFIX = "Spec.Instr."

# 导出行 → BlotterOrderRow 的列名映射（其余列进 extra_fields）
_ROW_FIELD_COLUMNS = {
    "code": "Code",
    "exch_code": "Exch Code",
    "name": "Name",
    "side": "Side",
    "qty": "Qty",
    "ccy": "Curncy",
    "status": "Status",
    "fill_qty": "FillQty",
    "pct_filled": "%Filled",
    "q_pct_5d_adv": "Q% 5D ADV",
    "q_pct_tdy": "Q % tdy",
    "rem_bal_pct_avg_cls_auct_vol": "Rem Bal % Avg Cls Auct Vol",
    "working_val_usd": "Working Val (USD)",
    "value_usd": "$value",
    "chg_pct_dtdy": "% Chg D Tdy",
    "last_px_vs_vwap_bps": "LastPx Vs VWAP (Bps)",
    "earn_rpt_time": "Exp Earn Rpt Time",
    "ex_dvd_flag": "Ex-Dvd Flag",
    "brkr_code": "Brkr Code",
    "create_time": "Create Time (As of)",
    "pm_note": "PM Note 13",
}
_ROW_TEXT_FIELDS = ("code", "exch_code", "name", "side", "ccy", "status", "brkr_code", "create_time", "pm_note")
_ROW_FLOAT_FIELDS = (
    "qty",
    "fill_qty",
    "pct_filled",
    "q_pct_5d_adv",
    "q_pct_tdy",
    "rem_bal_pct_avg_cls_auct_vol",
    "working_val_usd",
    "value_usd",
    "chg_pct_dtdy",
    "last_px_vs_vwap_bps",
)


class ExportParseError(ValueError):
    """导出解析错误：缺关键列或字段数与表头不符（detail 可见列名/行号）。"""


@dataclass(frozen=True)
class ScannedExport:
    """收件箱中最新一份导出文件的元信息（不含目录路径，目录在仓库外）。"""

    file_name: str
    exported_at: str  # ISO 8601（UTC，取文件 mtime）
    size_bytes: int


@dataclass(frozen=True)
class ParsedExport:
    """按列名解析后的导出：表头（重名列已加后缀）与逐行清洗值（None=缺失/遮蔽/受限）。"""

    file_name: str
    header: list[str]
    rows: list[dict[str, str | None]]


# ── 收件箱扫描 ─────────────────────────────────────────────────────────────────


def scan_latest_export(inbox_dir: str) -> ScannedExport | None:
    """按 mtime 取收件箱里最新一份 .csv 导出；目录不存在或无文件返回 None。"""
    inbox = Path(inbox_dir)
    if not inbox.is_dir():
        return None
    csv_files = [p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]
    if not csv_files:
        return None
    latest = max(csv_files, key=lambda p: p.stat().st_mtime)
    stat = latest.stat()
    exported_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return ScannedExport(file_name=latest.name, exported_at=exported_at, size_bytes=stat.st_size)


# ── CSV 解析 ───────────────────────────────────────────────────────────────────


def parse_export_csv(text: str, *, file_name: str) -> ParsedExport:
    """按列名解析导出文本。

    - csv.reader 逐行严格校验：行宽与表头不符即报错（不用会静默错位的 DictReader）；
    - 重名列按出现顺序加 ` (2)` 后缀；
    - 遮蔽值与受限标记按缺失（None）处理；空串同样按缺失。
    """
    reader = csv.reader(text.splitlines())
    try:
        header = next(reader)
    except StopIteration:
        raise ExportParseError(f"{file_name}: 导出文件为空（无表头行）") from None

    unique_header = _dedupe_header(header, file_name=file_name)
    missing = [col for col in REQUIRED_COLUMNS if col not in set(unique_header)]
    if missing:
        raise ExportParseError(f"{file_name}: 导出缺少关键列 {missing}")

    rows: list[dict[str, str | None]] = []
    for line_no, raw in enumerate(reader, start=2):
        if not raw:  # 尾部空行
            continue
        if len(raw) != len(unique_header):
            raise ExportParseError(
                f"{file_name}: 第 {line_no} 行字段数 {len(raw)} 与表头 {len(unique_header)} 不符"
            )
        rows.append({col: _clean_value(val) for col, val in zip(unique_header, raw)})
    return ParsedExport(file_name=file_name, header=unique_header, rows=rows)


def _dedupe_header(header: list[str], *, file_name: str) -> list[str]:
    """重名列按出现顺序加 ` (2)` 后缀（附录 A 样例的 `Day Part Rate %` 出现两次）。"""
    seen: dict[str, int] = {}
    unique: list[str] = []
    for col in header:
        count = seen.get(col, 0)
        seen[col] = count + 1
        unique.append(col if count == 0 else f"{col} ({count + 1})")
    if len(set(unique)) != len(unique):
        raise ExportParseError(f"{file_name}: 表头存在无法去重的列（{header}）")
    return unique


def _clean_value(raw: str | None) -> str | None:
    """遮蔽值、受限标记与空串一律按缺失（None）处理。"""
    if raw is None:
        return None
    value = raw.strip()
    if not value or value in _MASKED_VALUES or value == RESTRICTED_MARKER:
        return None
    return value


def _to_optional_float(raw: str | None) -> float | None:
    """数值列解析；容忍千分位逗号；失败按缺失（导出可能出现异常拼接值）。"""
    if raw is None:
        return None
    try:
        return float(raw.replace(",", ""))
    except (TypeError, ValueError):
        return None


# ── PM Note 意图映射 ───────────────────────────────────────────────────────────


def parse_pm_note(raw_note: str | None, *, export_ts: str, valid_from: str | None = None) -> OrderIntent:
    """按第一个 `^` 切开 PM Note 13：前缀定意图，`^` 段作连接键。

    空前缀 → VWAP；「数字 % @Close」→ CLOSE（100）/ MIX（其余）；
    `Spec.Instr.` → SPECIAL；其他前缀 → UNMAPPED。空 note → UNMAPPED。
    无 `^` 段时意图可映射但 order_key 为空（missing_order_key，进未匹配清单）。
    """
    note = (raw_note or "").strip()
    valid = valid_from or export_ts
    if not note:
        return OrderIntent(
            order_key="",
            benchmark="UNMAPPED",
            close_pct=None,
            raw_note=raw_note or "",
            intent_source=INTENT_SOURCE_EMSX_EXPORT,
            valid_from=valid,
            export_ts=export_ts,
            unmatched_reason="empty_pm_note",
        )

    prefix, sep, key_part = note.partition("^")
    order_key = f"^{key_part}" if sep else ""

    benchmark = "UNMAPPED"
    close_pct: float | None = None
    reason: str | None = None
    if not prefix.strip():
        benchmark = "VWAP"
    else:
        match = _CLOSE_PCT_PATTERN.match(prefix)
        if match:
            close_pct = float(match.group(1))
            benchmark = "CLOSE" if close_pct >= 100.0 else "MIX"
        elif prefix.strip().startswith(_SPECIAL_PREFIX):
            benchmark = "SPECIAL"
        else:
            reason = "unknown_prefix"

    if benchmark != "UNMAPPED" and not order_key:
        reason = "missing_order_key"

    return OrderIntent(
        order_key=order_key,
        benchmark=benchmark,
        close_pct=close_pct,
        raw_note=note,
        intent_source=INTENT_SOURCE_EMSX_EXPORT,
        valid_from=valid,
        export_ts=export_ts,
        unmatched_reason=reason,
    )


# ── 盘前单组装 ─────────────────────────────────────────────────────────────────


def build_pre_trade_board(parsed: ParsedExport, scanned: ScannedExport) -> PreTradeOrderBoard:
    """逐行解析意图、统计连接覆盖率、收集未匹配清单。"""
    export_ts = scanned.exported_at
    orders = [_build_row(row, export_ts=export_ts) for row in parsed.rows]
    unmatched = [
        UnmatchedOrder(code=order.code, pm_note=order.pm_note, reason=order.intent.unmatched_reason or "")
        for order in orders
        if order.intent.unmatched_reason
    ]
    matched_count = len(orders) - len(unmatched)
    coverage = round(matched_count / len(orders) * 100.0, 2) if orders else 0.0
    return PreTradeOrderBoard(
        exported_at=export_ts,
        export_file_name=parsed.file_name,
        order_count=len(orders),
        intent_coverage_pct=coverage,
        orders=orders,
        unmatched=unmatched,
        intent_mapping_version=INTENT_MAPPING_VERSION,
    )


def load_pre_trade_board(inbox_dir: str) -> PreTradeOrderBoard | None:
    """收件箱 → 盘前单的一体入口；目录未配置/无导出返回 None。"""
    scanned = scan_latest_export(inbox_dir)
    if scanned is None:
        return None
    text = Path(inbox_dir, scanned.file_name).read_text(encoding="utf-8-sig")
    parsed = parse_export_csv(text, file_name=scanned.file_name)
    return build_pre_trade_board(parsed, scanned)


def _build_row(row: dict[str, str | None], *, export_ts: str) -> BlotterOrderRow:
    """一行导出 → BlotterOrderRow：关键列类型化，其余列进 extra_fields。"""
    values: dict[str, str | float | None] = {}
    for field_name, column in _ROW_FIELD_COLUMNS.items():
        raw = row.get(column)
        values[field_name] = _to_optional_float(raw) if field_name in _ROW_FLOAT_FIELDS else raw

    extra = {
        col: val
        for col, val in row.items()
        if col not in set(_ROW_FIELD_COLUMNS.values()) and val is not None
    }
    intent = parse_pm_note(row.get("PM Note 13"), export_ts=export_ts)
    return BlotterOrderRow(
        code=values["code"] or "",
        exch_code=values["exch_code"] or "",
        name=values["name"] or "",
        side=values["side"] or "",
        qty=values["qty"] if isinstance(values["qty"], float) else None,
        ccy=values["ccy"] or "",
        status=values["status"] or "",
        fill_qty=values["fill_qty"] if isinstance(values["fill_qty"], float) else None,
        pct_filled=values["pct_filled"] if isinstance(values["pct_filled"], float) else None,
        q_pct_5d_adv=values["q_pct_5d_adv"] if isinstance(values["q_pct_5d_adv"], float) else None,
        q_pct_tdy=values["q_pct_tdy"] if isinstance(values["q_pct_tdy"], float) else None,
        rem_bal_pct_avg_cls_auct_vol=(
            values["rem_bal_pct_avg_cls_auct_vol"]
            if isinstance(values["rem_bal_pct_avg_cls_auct_vol"], float)
            else None
        ),
        working_val_usd=values["working_val_usd"] if isinstance(values["working_val_usd"], float) else None,
        value_usd=values["value_usd"] if isinstance(values["value_usd"], float) else None,
        chg_pct_dtdy=values["chg_pct_dtdy"] if isinstance(values["chg_pct_dtdy"], float) else None,
        last_px_vs_vwap_bps=(
            values["last_px_vs_vwap_bps"] if isinstance(values["last_px_vs_vwap_bps"], float) else None
        ),
        earn_rpt_time=values["earn_rpt_time"] if isinstance(values["earn_rpt_time"], str) else None,
        ex_dvd_flag=values["ex_dvd_flag"] if isinstance(values["ex_dvd_flag"], str) else None,
        brkr_code=values["brkr_code"] or "",
        create_time=values["create_time"] or "",
        pm_note=values["pm_note"] or "",
        intent=intent,
        extra_fields=extra,
    )
