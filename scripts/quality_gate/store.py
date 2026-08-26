"""SQLite 持久化 — scans / findings / baseline 三表。

基线生命周期：
- full 扫描：upsert 全部 finding + 标记本轮未见的 open 项为 fixed
- staged 扫描：仅 upsert（不标记 fixed — 覆盖面不完整）
- suppressed：人工豁免，扫描输出/报告/门禁全部跳过
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Finding, ScanResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    scan_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    trigger    TEXT NOT NULL,
    mode       TEXT NOT NULL,
    git_sha    TEXT,
    branch     TEXT,
    n_findings INTEGER NOT NULL,
    td_hours   REAL NOT NULL,
    python_loc INTEGER NOT NULL,
    files_scanned INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    scan_id     INTEGER NOT NULL REFERENCES scans(scan_id),
    fingerprint TEXT NOT NULL,
    ruleset     TEXT NOT NULL,
    rule_id     TEXT NOT NULL,
    severity    TEXT NOT NULL,
    file        TEXT NOT NULL,
    line        INTEGER NOT NULL,
    symbol      TEXT NOT NULL,
    message     TEXT NOT NULL,
    fix_hint    TEXT NOT NULL,
    est_effort_h REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_scan ON findings(scan_id);
CREATE TABLE IF NOT EXISTS baseline (
    fingerprint TEXT PRIMARY KEY,
    ruleset     TEXT NOT NULL,
    rule_id     TEXT NOT NULL,
    file        TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    status      TEXT NOT NULL,
    note        TEXT
);
"""


class GateStore:
    """质量门禁趋势库。"""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)

    # ── 扫描记录 ──────────────────────────────────────────────────

    def save_scan(self, result: ScanResult) -> int:
        """落盘一次扫描（scans + findings）。"""
        cur = self._conn.execute(
            "INSERT INTO scans (ts, trigger, mode, git_sha, branch, n_findings,"
            " td_hours, python_loc, files_scanned) VALUES (?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), result.trigger, result.mode,
             result.git_sha, result.branch, len(result.findings), result.td_hours,
             result.python_loc, result.files_scanned))
        scan_id = int(cur.lastrowid or 0)
        self._conn.executemany(
            "INSERT INTO findings (scan_id, fingerprint, ruleset, rule_id, severity,"
            " file, line, symbol, message, fix_hint, est_effort_h)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(scan_id, f.fingerprint, f.ruleset.value, f.rule_id, f.severity.value,
              f.file, f.line, f.symbol, f.message, f.fix_hint, f.est_effort_h)
             for f in result.findings])
        self._conn.commit()
        return scan_id

    def last_full_scan(self) -> dict | None:
        """最近一次全量扫描记录（趋势环比用）。"""
        row = self._conn.execute(
            "SELECT scan_id, ts, n_findings, td_hours, python_loc FROM scans"
            " WHERE mode='full' ORDER BY scan_id DESC LIMIT 1").fetchone()
        return _row_to_dict(row, ["scan_id", "ts", "n_findings", "td_hours", "python_loc"]) \
            if row else None

    def history(self, limit: int = 8) -> list[dict]:
        """最近 N 次全量扫描（报告趋势表）。"""
        rows = self._conn.execute(
            "SELECT scan_id, ts, n_findings, td_hours, python_loc FROM scans"
            " WHERE mode='full' ORDER BY scan_id DESC LIMIT ?", (limit,)).fetchall()
        cols = ["scan_id", "ts", "n_findings", "td_hours", "python_loc"]
        return [_row_to_dict(r, cols) for r in rows]

    # ── 基线维护 ──────────────────────────────────────────────────

    def upsert_baseline(self, findings: list[Finding]) -> None:
        """upsert 基线：新 fingerprint 建档 open；fixed 的重现改回 open。"""
        now = datetime.now().isoformat(timespec="seconds")
        for f in findings:
            self._conn.execute(
                "INSERT INTO baseline (fingerprint, ruleset, rule_id, file,"
                " first_seen, last_seen, status, note)"
                " VALUES (?,?,?,?,?,?, 'open', NULL)"
                " ON CONFLICT(fingerprint) DO UPDATE SET"
                " last_seen=excluded.last_seen,"
                " status=CASE WHEN baseline.status='fixed' THEN 'open'"
                "            ELSE baseline.status END",
                (f.fingerprint, f.ruleset.value, f.rule_id, f.file, now, now))
        self._conn.commit()

    def mark_fixed_missing(self, seen: set[str]) -> int:
        """full 扫描后：open 且本轮未见的 fingerprint 标记 fixed，返回数量。"""
        if seen:
            placeholders = ",".join("?" * len(seen))
            cur = self._conn.execute(
                "UPDATE baseline SET status='fixed'"
                f" WHERE status='open' AND fingerprint NOT IN ({placeholders})",
                tuple(seen))
        else:
            # 零 finding：全部 open 基线视为已清偿
            cur = self._conn.execute(
                "UPDATE baseline SET status='fixed' WHERE status='open'")
        self._conn.commit()
        return cur.rowcount or 0

    def load_open_fingerprints(self, ruleset: str = "oe") -> set[str]:
        """当前 open 状态的 fingerprint 集合（OE guard 门禁的已知集合）。"""
        rows = self._conn.execute(
            "SELECT fingerprint FROM baseline WHERE status='open' AND ruleset=?",
            (ruleset,)).fetchall()
        return {r[0] for r in rows}

    def load_suppressed(self) -> set[str]:
        """suppressed 的 fingerprint 集合（扫描结果全局过滤）。"""
        rows = self._conn.execute(
            "SELECT fingerprint FROM baseline WHERE status='suppressed'").fetchall()
        return {r[0] for r in rows}

    def suppress(self, fingerprint: str, note: str) -> bool:
        """人工豁免；fingerprint 不存在返回 False。"""
        cur = self._conn.execute(
            "UPDATE baseline SET status='suppressed', note=? WHERE fingerprint=?",
            (note, fingerprint))
        self._conn.commit()
        return bool(cur.rowcount)

    def baseline_summary(self) -> dict[str, int]:
        """基线状态统计（报告用）。"""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) FROM baseline GROUP BY status").fetchall()
        return {status: count for status, count in rows}

    def open_baseline_for_files(self, files: set[str]) -> dict[str, str]:
        """指定文件集合内 open 的 fingerprint → 规则 ID 映射（staged 修复提示用）。"""
        if not files:
            return {}
        placeholders = ",".join("?" * len(files))
        rows = self._conn.execute(
            "SELECT fingerprint, rule_id FROM baseline"
            f" WHERE status='open' AND ruleset='oe' AND file IN ({placeholders})",
            tuple(files)).fetchall()
        return {fp: rule for fp, rule in rows}

    def close(self) -> None:
        """关闭连接。"""
        self._conn.close()


def _row_to_dict(row: tuple, cols: list[str]) -> dict:
    """行 → 字典。"""
    return dict(zip(cols, row))
