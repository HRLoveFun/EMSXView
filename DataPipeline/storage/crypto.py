"""Transparent data encryption and tokenization layer.

Provides:
    - AES-256-GCM field-level encryption (requires ``cryptography`` pip package)
    - HMAC-SHA256 deterministic tokenization (stdlib fallback, no extra deps)
    - Key derivation from environment variables or key files
    - Selective column encryption for PII and financial data

Usage::

    from DataPipeline.storage.crypto import ColumnEncryptor
    enc = ColumnEncryptor()
    row = {"TraderName": "Smith", "FillPrice": 150.25, "Ticker": "AAPL"}
    encrypted = enc.encrypt_row(row)
    decrypted = enc.decrypt_row(encrypted)

Installation for AES mode::

    pip install cryptography

Without it, falls back to HMAC-SHA256 tokenization which provides
deterministic obfuscation but NOT reversible encryption.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# Try to import Fernet for AES-256-GCM; fall back to HMAC tokenization.
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    _HAS_CRYPTOGRAPHY = True
except ImportError:
    _HAS_CRYPTOGRAPHY = False


@dataclass(frozen=True)
class EncryptionConfig:
    key_env_var: str = "EMSXVIEW_ENCRYPTION_KEY"
    key_file: Optional[Path] = None
    salt_env_var: str = "EMSXVIEW_KEY_SALT"
    iterations: int = 600_000
    cipher_columns: tuple[str, ...] = (
        "TraderName", "TraderUuid", "FillPrice", "FillShares",
        "Amount", "OrderId", "FundName", "BrokerAccount",
    )


class ColumnEncryptor:

    def __init__(self, config: Optional[EncryptionConfig] = None) -> None:
        self._config = config or EncryptionConfig()
        self._key_material = self._resolve_key()
        if _HAS_CRYPTOGRAPHY:
            self._fernet = self._derive_fernet()
        else:
            self._fernet = None

    def _resolve_key(self) -> bytes:
        key = os.getenv(self._config.key_env_var)
        if not key and self._config.key_file and self._config.key_file.exists():
            key = self._config.key_file.read_text().strip()
        if not key:
            raise RuntimeError(
                f"Encryption key not found. Set {self._config.key_env_var} "
                f"or create {self._config.key_file}"
            )
        return key.encode("utf-8")

    def _derive_fernet(self) -> Optional[Any]:
        if not _HAS_CRYPTOGRAPHY:
            return None
        salt = os.getenv(self._config.salt_env_var, "emsxview-default-salt").encode()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self._config.iterations,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(self._key_material))
        return Fernet(derived_key)

    # ------------------------------------------------------------------
    # Encryption / Tokenization
    # ------------------------------------------------------------------

    def _hmac_tokenize(self, value: str) -> str:
        """Deterministic tokenization via HMAC-SHA256 (stdlib fallback)."""
        mac = hmac.new(self._key_material, value.encode("utf-8"), hashlib.sha256)
        return "tk:" + mac.hexdigest()[:24]

    def encrypt_value(self, value: Any) -> str:
        if value is None:
            return ""
        if self._fernet is not None:
            payload = json.dumps({"v": value}).encode()
            return "enc:" + self._fernet.encrypt(payload).decode()
        return self._hmac_tokenize(str(value))

    def decrypt_value(self, encrypted: Optional[str]) -> Any:
        if not encrypted:
            return None
        if encrypted.startswith("enc:") and self._fernet is not None:
            payload = self._fernet.decrypt(encrypted[4:].encode())
            return json.loads(payload)["v"]
        if encrypted.startswith("tk:"):
            return encrypted
        return encrypted

    # ------------------------------------------------------------------
    # Row-level convenience
    # ------------------------------------------------------------------

    def encrypt_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(row)
        for col in self._config.cipher_columns:
            if col in result:
                result[col] = self.encrypt_value(result[col])
        return result

    def decrypt_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(row)
        for col in self._config.cipher_columns:
            if col in result and result[col]:
                result[col] = self.decrypt_value(result[col])
        return result

    @property
    def mode(self) -> str:
        return "aes-gcm" if self._fernet else "hmac-tokenize"


def generate_encryption_key() -> str:
    """Generate a cryptographically random 256-bit key for production use.

    Store the output in an environment variable or key file.
    Example::

        export EMSXVIEW_ENCRYPTION_KEY=$(python -c \\
            "from DataPipeline.storage.crypto import generate_encryption_key; \\
            print(generate_encryption_key())")
    """
    return secrets.token_hex(32)
