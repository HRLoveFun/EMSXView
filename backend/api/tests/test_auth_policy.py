"""Tests for auth_service — auth mode matrix and policy checks."""

import pytest
from unittest.mock import patch, MagicMock

from services.auth_service import authenticate, check_trader_ownership, is_admin


class TestAuthenticate:
    """Test authenticate() across auth modes."""

    def test_bypass_mode_returns_fixed_identity(self):
        """In bypass mode, authenticate returns a fixed trader identity."""
        with patch("services.auth_service.settings") as mock_settings:
            mock_settings.BYPASS_AUTH = True
            result = authenticate(None)
            assert result["sub"] == "bloomberg_local"
            assert result["role"] == "trader"

    def test_bypass_mode_ignores_token(self):
        """In bypass mode, any token is ignored."""
        with patch("services.auth_service.settings") as mock_settings:
            mock_settings.BYPASS_AUTH = True
            result = authenticate("any-token")
            assert result["sub"] == "bloomberg_local"

    def test_jwt_mode_no_token_raises_401(self):
        """In JWT mode, missing token raises 401."""
        with patch("services.auth_service.settings") as mock_settings:
            mock_settings.BYPASS_AUTH = False
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                authenticate(None)
            assert exc_info.value.status_code == 401

    def test_jwt_mode_empty_token_raises_401(self):
        """In JWT mode, empty string token raises 401."""
        with patch("services.auth_service.settings") as mock_settings:
            mock_settings.BYPASS_AUTH = False
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                authenticate("")
            assert exc_info.value.status_code == 401

    def test_jwt_mode_valid_token_delegates_to_auth_manager(self):
        """In JWT mode, valid token is passed to AuthManager.verify_token."""
        with patch("services.auth_service.settings") as mock_settings, \
             patch("services.auth_service.AuthManager") as mock_auth:
            mock_settings.BYPASS_AUTH = False
            mock_auth.verify_token.return_value = {"sub": "trader1", "role": "trader"}
            result = authenticate("valid-jwt-token")
            mock_auth.verify_token.assert_called_once_with("valid-jwt-token")
            assert result["sub"] == "trader1"

    def test_jwt_mode_invalid_token_propagates_exception(self):
        """In JWT mode, AuthManager raising HTTPException is propagated."""
        with patch("services.auth_service.settings") as mock_settings, \
             patch("services.auth_service.AuthManager") as mock_auth:
            mock_settings.BYPASS_AUTH = False
            from fastapi import HTTPException
            mock_auth.verify_token.side_effect = HTTPException(401, "Invalid token")
            with pytest.raises(HTTPException) as exc_info:
                authenticate("bad-token")
            assert exc_info.value.status_code == 401


class TestTraderOwnership:
    """Test check_trader_ownership() policy."""

    def test_bypass_always_grants(self):
        with patch("services.auth_service.settings") as mock_settings:
            mock_settings.BYPASS_AUTH = True
            assert check_trader_ownership({}, "anyone") is True

    def test_matching_sub_grants(self):
        with patch("services.auth_service.settings") as mock_settings:
            mock_settings.BYPASS_AUTH = False
            assert check_trader_ownership({"sub": "TRADER1"}, "trader1") is True

    def test_mismatch_sub_denies(self):
        with patch("services.auth_service.settings") as mock_settings:
            mock_settings.BYPASS_AUTH = False
            assert check_trader_ownership({"sub": "TRADER1"}, "trader2") is False


class TestIsAdmin:
    """Test is_admin() check."""

    def test_admin_role(self):
        assert is_admin({"role": "admin"}) is True

    def test_trader_role(self):
        assert is_admin({"role": "trader"}) is False

    def test_missing_role(self):
        assert is_admin({}) is False
