"""跨市场实时订阅探针（057 DL-15 / 057 DL-29 配套诊断工具）。

按「一次性订阅全部样本 → 汇总字段可用性」核对 `//blp/mktdata` 的实际推送面。
字段可用性同时依赖**市场**与**交易时段**：休市市场仍返回上一交易日的镜像值，
只有开盘市场才有持续推送；因此结论必须带上探针时刻与样本市场。

用法：
    python scripts/diagnose/blpapi_mktdata_probe.py --tickers "AAPL US Equity,700 HK Equity"
    python scripts/diagnose/blpapi_mktdata_probe.py --tickers-file samples.txt --seconds 20
    python scripts/diagnose/blpapi_mktdata_probe.py --tickers-file samples.txt --json out.json

`--tickers-file` 每行一个样本，支持 `EXCHANGE,TICKER` 或 `TICKER`，`#` 开头为注释。

输出三段：逐样本矩阵（`-` = 元素缺失、`null` = 元素存在但无值、`ok` = 有值）、
逐字段覆盖（触及 / 有值 / 空值）、订阅失败清单。

判读要点（2026-10-28 实测 34 个市场、67 个样本）：
    - BID/ASK/LAST/OPEN/HIGH/LOW/VOLUME/MID 在休市市场同样有镜像值，不等于「在跳」；
      只有开盘市场的事件数持续增长。
    - CHG_PCT_1D / NET_CHG_PCT_1D / PX_CLOSE_1D / VOLUME_AVG_5D / VOLUME_AVG_20D /
      PX_ROUND_LOT_SIZE 不在 mktdata 推送面（全市场 0 次触及）；涨跌幅走
      PREV_CLOSE_VALUE_REALTIME 回落。
    - VWAP 仅部分市场有真实值（AU/IJ/IN/JP/KS/MK/NZ/SP），EU/US 返回 0.00，HK/CN 缺失。
    - BID_SIZE / ASK_SIZE 在丹麦（DC）、瑞典（SS）整体缺失，IT/SW/IJ 部分缺失。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

import blpapi

# 应用实际消费的字段 + 曾评估过的候选字段（后者用于复验「是否可订阅」）
DEFAULT_FIELDS = [
    "BID", "ASK", "BID_SIZE", "ASK_SIZE",
    "LAST_PRICE", "MID", "OPEN", "HIGH", "LOW", "VOLUME",
    "PREV_CLOSE_VALUE_REALTIME", "CHG_PCT_1D",
    "VWAP", "VOLUME_AVG_5D", "VOLUME_AVG_20D", "PX_ROUND_LOT_SIZE",
]
# 判定「是否在跳」的观察字段
WATCH_FIELD = "LAST_PRICE"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """命令行参数：样本来源、窗口长度、字段集、输出位置。"""
    parser = argparse.ArgumentParser(description="//blp/mktdata 跨市场字段可用性探针")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tickers", help="逗号分隔的样本（可写 EXCHANGE,TICKER）")
    source.add_argument("--tickers-file", help="样本文件：每行 EXCHANGE,TICKER 或 TICKER")
    parser.add_argument("--seconds", type=float, default=20.0, help="观察窗口（默认 20 秒）")
    parser.add_argument("--fields", help="逗号分隔的测试字段集（默认应用字段 + 候选字段）")
    parser.add_argument("--host", default="localhost", help="Bloomberg 终端主机（默认 localhost）")
    parser.add_argument("--port", type=int, default=8194, help="B-PIPE/终端端口（默认 8194）")
    parser.add_argument("--json", help="把完整结果写入该 JSON 文件")
    return parser.parse_args(argv)


def load_samples(args: argparse.Namespace) -> list[tuple[str, str]]:
    """返回 [(label, ticker)]；label 缺省为 ticker 本身。"""
    if args.tickers:
        rows = [part.strip() for part in args.tickers.split(",") if part.strip()]
    else:
        with open(args.tickers_file, encoding="utf-8") as handle:
            rows = [line.strip() for line in handle if line.strip() and not line.startswith("#")]
    samples: list[tuple[str, str]] = []
    for row in rows:
        label, _, ticker = row.rpartition(",")
        samples.append((label.strip() or ticker.strip(), ticker.strip()))
    return samples


def open_session(host: str, port: int) -> blpapi.Session:
    """建立会话并打开 //blp/mktdata；失败抛 RuntimeError（调用方转成退出码）。"""
    options = blpapi.SessionOptions()
    options.setServerHost(host)
    options.setServerPort(port)
    options.setAutoRestartOnDisconnection(False)
    session = blpapi.Session(options)
    if not session.start():
        raise RuntimeError("blpapi 会话启动失败（终端/BBComm 未运行？）")
    if not session.openService("//blp/mktdata"):
        session.stop()
        raise RuntimeError("打开 //blp/mktdata 失败（权限或服务名有误）")
    return session


def subscribe(session: blpapi.Session, samples: list[tuple[str, str]], fields: list[str]) -> None:
    """单批订阅；correlationId 用 ticker 本身，省掉映射表。"""
    subscriptions = blpapi.SubscriptionList()
    for _, ticker in samples:
        subscriptions.add(
            topic=f"//blp/mktdata/{ticker}",
            fields=fields,
            correlationId=blpapi.CorrelationId(ticker),
        )
    session.subscribe(subscriptions)


def _field_value(element):
    """元素存在时的取值：isNull → None（区分「缺失」与「无值」）。"""
    if element.isNull():
        return None
    try:
        return element.getValue()
    except Exception:  # noqa: BLE001 - 单字段解析失败不打断整条消息
        return "error"


def _apply_message(state: dict, msg, event_type, fields: list[str]) -> None:
    """把一条消息并入样本状态（状态机：subscribed → streaming / failed）。"""
    cid = msg.correlationId()
    entry = state.get(str(cid.value())) if cid else None
    if entry is None:
        return
    message_type = str(msg.messageType())
    if message_type in ("SubscriptionFailure", "SubscriptionTerminated"):
        entry["status"] = message_type
        if msg.hasElement("reason"):
            entry["reason"] = str(msg.getElement("reason"))
        return
    if message_type == "SubscriptionStarted":
        entry["status"] = "subscribed"
        return
    if event_type != blpapi.Event.SUBSCRIPTION_DATA:
        return
    entry["status"] = "streaming"
    entry["events"] += 1
    for field in fields:
        if msg.hasElement(field):
            entry["fields"][field] = _field_value(msg.getElement(field))
    watched = entry["fields"].get(WATCH_FIELD)
    if watched is not None:
        entry.setdefault("watch_first", watched)
        entry["watch_last"] = watched


def collect(session: blpapi.Session, samples: list[tuple[str, str]], fields: list[str],
            seconds: float) -> dict:
    """事件泵：在窗口内累积每个样本的字段快照与事件计数。"""
    state = {
        ticker: {"label": label, "status": "no_event", "events": 0, "fields": {}}
        for label, ticker in samples
    }
    deadline = time.time() + seconds
    while time.time() < deadline:
        event = session.nextEvent(500)
        for msg in event:
            _apply_message(state, msg, event.eventType(), fields)
    return state


def _cell(fields: dict, field: str) -> str:
    """矩阵单元格：`-` 缺失 / `null` 无值 / 有值则打印数值。"""
    if field not in fields:
        return "-"
    value = fields[field]
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_matrix(state: dict, fields: list[str]) -> list[str]:
    """逐样本矩阵：样本 / 状态 / 事件数 / 各字段。"""
    header = f"{'SAMPLE':16} {'STATUS':20} {'EV':>6} " + " ".join(
        f"{field[:12]:>12}" for field in fields
    )
    lines = [f"probed_at {datetime.now().isoformat(timespec='seconds')}", header]
    for ticker, entry in sorted(state.items(), key=lambda item: item[1]["label"]):
        cells = " ".join(f"{_cell(entry['fields'], field):>12}" for field in fields)
        lines.append(f"{entry['label'][:16]:16} {entry['status']:20} {entry['events']:6d} {cells}")
    return lines


def render_coverage(state: dict, fields: list[str]) -> list[str]:
    """逐字段覆盖：触及（元素出现）× 有值 × 空值。"""
    lines = ["", "=== 字段覆盖（触及 / 有值 / 空值）==="]
    for field in fields:
        touched = sum(1 for entry in state.values() if field in entry["fields"])
        nulls = sum(1 for entry in state.values() if entry["fields"].get(field, 1) is None)
        lines.append(f"{field:28} touched={touched:3d} value={touched - nulls:3d} null={nulls:3d}")
    return lines


def render_failures(state: dict) -> list[str]:
    """订阅失败与无数据清单（不静默吞掉）。"""
    lines = ["", "=== 订阅失败 / 无数据 ==="]
    broken = [(ticker, entry) for ticker, entry in state.items() if entry["status"] != "streaming"]
    if not broken:
        lines.append("(none)")
    for ticker, entry in sorted(broken, key=lambda item: item[1]["label"]):
        reason = entry.get("reason", "")
        lines.append(f"{entry['label']} [{ticker}] {entry['status']} {reason}".rstrip())
    return lines


def render_ticks(state: dict) -> list[str]:
    """哪些样本在窗口内真正跳动（区分「镜像值」与「实时在跳」）。"""
    ticking = [
        entry["label"] for entry in state.values()
        if entry.get("watch_first") is not None and entry.get("watch_first") != entry.get("watch_last")
    ]
    return ["", f"=== 窗口内 {WATCH_FIELD} 有跳动（{len(ticking)}/{len(state)}）===", ", ".join(ticking) or "(none)"]


def main(argv: list[str] | None = None) -> int:
    """入口：订阅 → 采集 → 三段报告（可选 JSON）。"""
    # Windows 控制台/重定向默认 cp1252，中文段头会编码失败
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # 极老解释器无 reconfigure
        pass
    args = parse_args(argv)
    fields = [field.strip() for field in args.fields.split(",")] if args.fields else DEFAULT_FIELDS
    samples = load_samples(args)
    if not samples:
        print("样本为空：请检查 --tickers / --tickers-file")
        return 2
    try:
        session = open_session(args.host, args.port)
    except RuntimeError as exc:
        print(f"FAILED: {exc}")
        return 1
    try:
        subscribe(session, samples, fields)
        state = collect(session, samples, fields, args.seconds)
    finally:
        session.stop()

    lines = render_matrix(state, fields) + render_coverage(state, fields) + render_ticks(state) \
        + render_failures(state)
    print("\n".join(lines))

    if args.json:
        payload = {
            "probed_at": datetime.now().isoformat(timespec="seconds"),
            "seconds": args.seconds,
            "fields": fields,
            "samples": state,
        }
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1, default=str)
        print(f"\nJSON: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
