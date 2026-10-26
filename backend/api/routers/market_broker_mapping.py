"""Market Broker Mapping router.

Persists which brokers are *allowed* for each market (exchange code), and
each market's *available-broker list* (roster). Edits to the roster are
password-gated because they represent company-counterparty relationships.

A01（审计 H1）写入闭环：
- `selection` 写入要求 `admin` 权限，且已启用项必须落在该市场 roster 内；
- roster/unlock 密码无默认值（未配置即 403）、常量时间比较、进程内限速；
- 审计操作人取 JWT 的 `sub`（缺失回落 `unknown`）。

Storage: JSON file under `api/data/market_broker_mapping.json`. The shape is:

    {
      "updatedAt": "ISO-8601",
      "rosters":   { "<marketKey>": ["BROKER_A", "BROKER_B", ...] },
      "selection": { "<marketKey>": { "BROKER_A": true, "BROKER_B": false } }
    }

`marketKey` is normally the exchange country code (e.g. "AU", "JP").
EUR-currency exchanges collapse into the single key "EUR".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import verify_token, require_permission, audit_log
from schemas import ApiResponse

logger = logging.getLogger("main")

router = APIRouter(tags=["MarketBrokerMapping"])

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "market_broker_mapping.json"
_LOCK = asyncio.Lock()

_DEFAULT_STATE: dict = {
    "updatedAt": None,
    "rosters": {},
    "selection": {},
}

# 密码失败限速（进程内，每用户 5 次 / 60 秒；成功即清零）
_PASSWORD_WINDOW_SECONDS = 60.0
_PASSWORD_MAX_FAILURES = 5
_password_failures: dict[str, deque[float]] = {}


def _admin_password() -> str | None:
    """Password required to edit broker rosters. Override via env.

    无默认值：未配置 `EMSX_MAPPING_ADMIN_PASSWORD` 时返回 None，写入一律 403
    （fail-closed），不再回落到众所周知的 "admin"。
    """
    value = os.getenv("EMSX_MAPPING_ADMIN_PASSWORD", "").strip()
    return value or None


def _password_rate_key(user: dict) -> str:
    """限速分桶键：JWT sub（缺失回落 unknown），避免低权限用户锁死他人。"""
    return str(user.get("sub") or "unknown")


def _prune_password_failures(key: str, now: float) -> deque[float]:
    """裁剪过期失败记录并返回该主体的当前窗口。"""
    bucket = _password_failures.setdefault(key, deque())
    while bucket and now - bucket[0] > _PASSWORD_WINDOW_SECONDS:
        bucket.popleft()
    return bucket


def _check_password_rate(user: dict, denied_action: str, details: dict) -> None:
    """失败次数超限 → 429（审计留痕；成功不计数、失败不清零）。"""
    key = _password_rate_key(user)
    if len(_prune_password_failures(key, time.monotonic())) >= _PASSWORD_MAX_FAILURES:
        audit_log(
            denied_action,
            user=key,
            details={**details, "reason": "rate_limited"},
        )
        raise HTTPException(status_code=429, detail="Too many password attempts — retry later")


def _record_password_failure(user: dict) -> None:
    """仅在比较失败时计入；成功路径由 _clear_password_failures 清零。"""
    key = _password_rate_key(user)
    _prune_password_failures(key, time.monotonic()).append(time.monotonic())


def _clear_password_failures(user: dict) -> None:
    _password_failures.pop(_password_rate_key(user), None)


def _password_matches(password: str, expected: str) -> bool:
    """常量时间比较；统一编码为 UTF-8 字节（非 ASCII 不再抛 TypeError）。"""
    try:
        return secrets.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))
    except (TypeError, AttributeError):
        return False


def _require_admin_password(
    password: str,
    *,
    denied_action: str,
    user: dict,
    details: dict,
) -> None:
    """校验 roster 密码：未配置拒绝、限速、常量时间比较。"""
    expected = _admin_password()
    if expected is None:
        audit_log(
            denied_action,
            user=user.get("sub") or "unknown",
            details={**details, "reason": "not_configured"},
        )
        raise HTTPException(status_code=403, detail="Admin password not configured")
    _check_password_rate(user, denied_action, details)
    if not _password_matches(password, expected):
        _record_password_failure(user)
        audit_log(
            denied_action,
            user=user.get("sub") or "unknown",
            details={**details, "reason": "invalid_password"},
        )
        raise HTTPException(status_code=403, detail="Invalid password")
    _clear_password_failures(user)


def _load() -> dict:
    try:
        if _DATA_PATH.exists():
            with _DATA_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults to tolerate old files
            return {**_DEFAULT_STATE, **data}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to read %s: %s — using defaults", _DATA_PATH, e)
    return dict(_DEFAULT_STATE)


def _save(state: dict) -> None:
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _DATA_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    tmp.replace(_DATA_PATH)


# ---------------------------------------------------------------------------
# Selection validation (A01)
# ---------------------------------------------------------------------------


def _storage_market_key(market_key: str) -> str:
    """落盘用 marketKey：strip().upper()，EU 还原为前端口径 EUR（DL-03 折叠）。"""
    text = str(market_key or "").strip().upper()
    return "EUR" if text == "EU" else text


def _market_code(market_key: str) -> str:
    """准入策略市场码：strip().upper() + EUR→EU（与 access_policy_service 读路径一致）。"""
    text = str(market_key or "").strip().upper()
    return "EU" if text == "EUR" else text


def _normalize_selection(selection: dict) -> dict[str, dict[str, bool]]:
    """归一 selection 键：市场按落盘口径、券商大写；同键冲突取「任一 true 即 true」。"""
    normalized: dict[str, dict[str, bool]] = {}
    for market, row in (selection or {}).items():
        target = normalized.setdefault(_storage_market_key(market), {})
        for broker, enabled in (row or {}).items():
            broker_key = str(broker or "").strip().upper()
            if not broker_key:
                continue
            target[broker_key] = bool(target.get(broker_key, False) or enabled)
    return normalized


def _normalized_rosters(state: dict) -> dict[str, set[str]]:
    """roster 按准入策略市场码索引，券商大写（与读路径生效键一致）。"""
    rosters: dict[str, set[str]] = {}
    for market, brokers in (state.get("rosters") or {}).items():
        code = _market_code(market)
        rosters.setdefault(code, set()).update(
            str(broker or "").strip().upper() for broker in (brokers or [])
        )
    return rosters


def _out_of_roster_entries(state: dict, selection: dict) -> list[dict]:
    """已启用（true）但不在该市场 roster 内的 selection 项。

    值为 false 的键不授予任何权限（前端会带全量默认矩阵），不参与校验。
    roster 未配置（market 归一后不在 rosters）时按「未配置」跳过，见 _unconfigured_markets。
    """
    rosters = _normalized_rosters(state)
    violations: list[dict] = []
    for market, row in _normalize_selection(selection).items():
        code = _market_code(market)
        if code not in rosters:
            continue
        for broker, enabled in row.items():
            if enabled and broker not in rosters[code]:
                violations.append({"market": code, "broker": broker})
    return violations


def _unconfigured_markets(state: dict, selection: dict) -> list[str]:
    """selection 中出现、但 rosters 未配置的市场（审计留痕用，按策略市场码）。"""
    rosters = _normalized_rosters(state)
    return sorted(
        {_market_code(market) for market in _normalize_selection(selection) if _market_code(market) not in rosters}
    )




# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SelectionPayload(BaseModel):
    """Per-market broker-selection checkboxes. Admin only (A01)."""
    selection: Dict[str, Dict[str, bool]]


class RosterPayload(BaseModel):
    """Update a market's available-broker list (password-gated)."""
    market: str = Field(..., min_length=1, max_length=16)
    brokers: List[str]
    password: str


class UnlockPayload(BaseModel):
    password: str
    market: Optional[str] = None  # Informational only


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/market-broker-mapping", response_model=ApiResponse)
async def get_mapping(user: dict = Depends(verify_token)) -> ApiResponse:
    """Return the full mapping state (rosters + selection)."""
    async with _LOCK:
        state = _load()
    return ApiResponse(
        success=True,
        data=state,
        message=f"Loaded mapping ({len(state.get('rosters', {}))} markets)",
    )


@router.put("/api/market-broker-mapping/selection", response_model=ApiResponse)
async def update_selection(
    payload: SelectionPayload,
    user: dict = Depends(require_permission("admin")),
) -> ApiResponse:
    """Update the Broker-allowed checkboxes (admin only).

    A01（审计 H1）：后端强制已启用项落在 `rosters[market]` 内，越界整体拒绝并
    返回越界清单；roster 未配置的市场按「未配置」跳过校验并审计留痕。
    """
    normalized = _normalize_selection(payload.selection)
    async with _LOCK:
        state = _load()
        out_of_roster = _out_of_roster_entries(state, normalized)
        unconfigured = _unconfigured_markets(state, normalized)
        if not out_of_roster:
            state["selection"] = normalized
            state["updatedAt"] = datetime.utcnow().isoformat() + "Z"
            _save(state)

    # 越界拒绝的审计与响应放在锁外（持锁期间不做非必要副作用）
    if out_of_roster:
        audit_log(
            "market_broker_mapping.selection.rejected",
            user=user.get("sub") or "unknown",
            details={
                "markets": list(normalized.keys()),
                "out_of_roster": out_of_roster,
            },
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Selection contains brokers outside roster",
                "out_of_roster": out_of_roster,
            },
        )

    audit_log(
        "market_broker_mapping.selection.update",
        user=user.get("sub") or "unknown",
        details={
            "markets": list(normalized.keys()),
            "rosters_unconfigured": unconfigured,
        },
    )
    if unconfigured:
        logger.warning(
            "selection updated for markets without roster (未配置，跳过范围校验): %s",
            unconfigured,
        )
    return ApiResponse(success=True, data=state, message="Selection updated")


@router.post("/api/market-broker-mapping/unlock", response_model=ApiResponse)
async def verify_unlock_password(
    payload: UnlockPayload,
    user: dict = Depends(verify_token),
) -> ApiResponse:
    """Verify admin password. Used to unlock row-editing in the UI."""
    _require_admin_password(
        payload.password,
        denied_action="market_broker_mapping.unlock.failed",
        user=user,
        details={"market": payload.market},
    )
    audit_log(
        "market_broker_mapping.unlock.ok",
        user=user.get("sub") or "unknown",
        details={"market": payload.market},
    )
    return ApiResponse(success=True, data={"unlocked": True}, message="Unlocked")


@router.put("/api/market-broker-mapping/roster", response_model=ApiResponse)
async def update_roster(
    payload: RosterPayload,
    user: dict = Depends(verify_token),
) -> ApiResponse:
    """Replace the available-broker list for one market. Password-gated."""
    _require_admin_password(
        payload.password,
        denied_action="market_broker_mapping.roster.unauthorized",
        user=user,
        details={"market": payload.market},
    )

    # De-duplicate + preserve order
    seen: set[str] = set()
    cleaned: List[str] = []
    for b in payload.brokers:
        b_norm = (b or "").strip().upper()
        if not b_norm or b_norm in seen:
            continue
        seen.add(b_norm)
        cleaned.append(b_norm)

    market_key = _storage_market_key(payload.market)
    async with _LOCK:
        state = _load()
        rosters = {_storage_market_key(k): list(v or []) for k, v in (state.get("rosters") or {}).items()}
        rosters[market_key] = cleaned
        state["rosters"] = rosters

        # Clamp selection for this market to the new roster
        selection = _normalize_selection(state.get("selection") or {})
        market_sel = dict(selection.get(market_key) or {})
        selection[market_key] = {b: bool(market_sel.get(b, False)) for b in cleaned}
        state["selection"] = selection

        state["updatedAt"] = datetime.utcnow().isoformat() + "Z"
        _save(state)

    audit_log(
        "market_broker_mapping.roster.update",
        user=user.get("sub") or "unknown",
        details={"market": payload.market, "count": len(cleaned)},
    )
    return ApiResponse(success=True, data=state, message=f"Roster updated for {payload.market}")
