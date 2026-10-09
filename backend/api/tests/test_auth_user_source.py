"""S10 (040) — 可配置用户源测试。

锁死行为：EMSXVIEW_USERS 配置用户优先于 DEMO_USERS；配置未命中/坏 JSON/
空配置时回落 DEMO_USERS（告警可见）；配置项缺关键字段被跳过。
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# import 链触发 config.settings 校验，须在首次 import 前备好环境变量
os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

import config as config_mod
from auth import pwd_context

_SECRET_HASH = pwd_context.hash("s3cret")


def _reload_auth(monkeypatch, users_json: str):
    monkeypatch.setattr(config_mod.settings, "EMSXVIEW_USERS", users_json)
    return importlib.reload(importlib.import_module("auth"))


def test_config_user_authenticates(monkeypatch):
    """配置用户登录成功，角色来自配置。"""
    users = json.dumps([{
        "username": "alice", "password_hash": _SECRET_HASH,
        "full_name": "Alice Trader", "role": "trader",
    }])
    auth = _reload_auth(monkeypatch, users)

    user = auth.AuthManager.authenticate_user("alice", "s3cret")
    assert user is not None
    assert user.username == "alice"
    assert user.role == "trader"
    assert user.full_name == "Alice Trader"

    # 密码错误拒绝
    assert auth.AuthManager.authenticate_user("alice", "wrong") is None


def test_config_authoritative_rejects_demo_users(monkeypatch):
    """S15/055 行为变更：配置存在即权威——demo 用户不再兜底（fail-closed）。"""
    users = json.dumps([{
        "username": "alice", "password_hash": _SECRET_HASH,
        "full_name": "Alice Trader", "role": "trader",
    }])
    auth = _reload_auth(monkeypatch, users)

    # demo 账号在配置用户存在时被拒绝（防配置正式用户后 demo 管理员仍可登录）
    assert auth.AuthManager.authenticate_user("trader1", "password") is None
    assert auth.AuthManager.authenticate_user("admin", "password") is None
    # 仅配置内用户可认证
    assert auth.AuthManager.authenticate_user("alice", "s3cret") is not None


def test_bad_json_falls_back_with_error(monkeypatch, caplog):
    """坏 JSON：ERROR 可见且回落 DEMO_USERS。"""
    with caplog.at_level(logging.ERROR, logger="auth"):
        auth = _reload_auth(monkeypatch, "{not-json")

    assert any("parse failed" in r.message for r in caplog.records)
    user = auth.AuthManager.authenticate_user("trader1", "password")
    assert user is not None


def test_empty_entry_skipped(monkeypatch):
    """缺 password_hash 的条目跳过，不影响其余配置用户。"""
    users = json.dumps([
        {"username": "ghost", "full_name": "No Hash", "role": "trader"},
        {"username": "bob", "password_hash": _SECRET_HASH,
         "full_name": "Bob", "role": "admin"},
    ])
    auth = _reload_auth(monkeypatch, users)

    assert auth.AuthManager.authenticate_user("ghost", "anything") is None
    user = auth.AuthManager.authenticate_user("bob", "s3cret")
    assert user is not None and user.role == "admin"


def test_empty_config_keeps_demo_users(monkeypatch, caplog):
    """未配置（现状）：DEMO_USERS 生效且告警可见。"""
    with caplog.at_level(logging.WARNING, logger="auth"):
        auth = _reload_auth(monkeypatch, "")

    assert any("DEMO_USERS" in r.message for r in caplog.records)
    user = auth.AuthManager.authenticate_user("admin", "password")
    assert user is not None and user.role == "admin"
