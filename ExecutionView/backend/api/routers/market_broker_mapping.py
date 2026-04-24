"""Market Broker Mapping router.

Persists which brokers are *allowed* for each market (exchange code), and
each market's *available-broker list* (roster). Edits to the roster are
password-gated because they represent company-counterparty relationships.

Storage: JSON file under ``api/data/market_broker_mapping.json``. The shape is:

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
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import verify_token, audit_log
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


def _admin_password() -> str:
    """Password required to edit broker rosters. Override via env."""
    return os.getenv("EMSX_MAPPING_ADMIN_PASSWORD", "admin")


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
# Schemas
# ---------------------------------------------------------------------------


class SelectionPayload(BaseModel):
    """Per-market broker-selection checkboxes. Does NOT need password."""
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
async def get_mapping(user: dict = Depends(verify_token)):
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
    user: dict = Depends(verify_token),
):
    """Update the Broker-allowed checkboxes. No password required.

    The selection map may reference any (market, broker) — even pairs not in
    the roster — the frontend is responsible for clamping to the roster.
    """
    async with _LOCK:
        state = _load()
        state["selection"] = payload.selection
        state["updatedAt"] = datetime.utcnow().isoformat() + "Z"
        _save(state)

    audit_log(
        "market_broker_mapping.selection.update",
        user=user.get("username", "unknown"),
        details={"markets": list(payload.selection.keys())},
    )
    return ApiResponse(success=True, data=state, message="Selection updated")


@router.post("/api/market-broker-mapping/unlock", response_model=ApiResponse)
async def verify_unlock_password(
    payload: UnlockPayload,
    user: dict = Depends(verify_token),
):
    """Verify admin password. Used to unlock row-editing in the UI."""
    if payload.password != _admin_password():
        audit_log(
            "market_broker_mapping.unlock.failed",
            user=user.get("username", "unknown"),
            details={"market": payload.market},
        )
        raise HTTPException(status_code=403, detail="Invalid password")

    audit_log(
        "market_broker_mapping.unlock.ok",
        user=user.get("username", "unknown"),
        details={"market": payload.market},
    )
    return ApiResponse(success=True, data={"unlocked": True}, message="Unlocked")


@router.put("/api/market-broker-mapping/roster", response_model=ApiResponse)
async def update_roster(
    payload: RosterPayload,
    user: dict = Depends(verify_token),
):
    """Replace the available-broker list for one market. Password-gated."""
    if payload.password != _admin_password():
        audit_log(
            "market_broker_mapping.roster.unauthorized",
            user=user.get("username", "unknown"),
            details={"market": payload.market},
        )
        raise HTTPException(status_code=403, detail="Invalid password")

    # De-duplicate + preserve order
    seen: set[str] = set()
    cleaned: List[str] = []
    for b in payload.brokers:
        b_norm = (b or "").strip().upper()
        if not b_norm or b_norm in seen:
            continue
        seen.add(b_norm)
        cleaned.append(b_norm)

    async with _LOCK:
        state = _load()
        rosters = dict(state.get("rosters") or {})
        rosters[payload.market] = cleaned
        state["rosters"] = rosters

        # Clamp selection for this market to the new roster
        selection = dict(state.get("selection") or {})
        market_sel = dict(selection.get(payload.market) or {})
        selection[payload.market] = {b: bool(market_sel.get(b, False)) for b in cleaned}
        state["selection"] = selection

        state["updatedAt"] = datetime.utcnow().isoformat() + "Z"
        _save(state)

    audit_log(
        "market_broker_mapping.roster.update",
        user=user.get("username", "unknown"),
        details={"market": payload.market, "count": len(cleaned)},
    )
    return ApiResponse(success=True, data=state, message=f"Roster updated for {payload.market}")
