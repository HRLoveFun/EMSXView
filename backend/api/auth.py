#!/usr/bin/env python3
"""
EMSXView Trading API - Authentication Module
Handles user authentication and authorization
"""

import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import jwt  # PyJWT（P2-6 整改：python-jose 已停维，迁移至 PyJWT）
from passlib.context import CryptContext
from fastapi import HTTPException

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configuration — 从 config.settings 读取，避免重复 os.getenv
from config import settings as _settings

logger = logging.getLogger(__name__)

JWT_SECRET = _settings.JWT_SECRET
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = _settings.JWT_EXPIRE_MINUTES
ALLOWED_TRADERS = [t.strip() for t in _settings.ALLOWED_TRADERS if t.strip()]


def _load_config_users() -> Dict[str, Dict[str, str]]:
    """解析 EMSXVIEW_USERS 配置用户源 (S10/040)。

    环境变量为 JSON 数组：
      [{"username": "...", "password_hash": "<bcrypt>", "full_name": "...", "role": "trader"}]
    解析失败或未配置时返回空 dict（回落 DEMO_USERS 并告警可见）。
    """
    raw = getattr(_settings, "EMSXVIEW_USERS", "")
    if not raw or not raw.strip():
        return {}
    try:
        entries = json.loads(raw)
        users: Dict[str, Dict[str, str]] = {}
        for e in entries:
            username = str(e.get("username", "")).strip()
            password_hash = str(e.get("password_hash", "")).strip()
            if not username or not password_hash:
                logger.error("EMSXVIEW_USERS entry missing username/password_hash — skipped")
                continue
            users[username] = {
                "password": password_hash,
                "full_name": str(e.get("full_name", username)),
                "role": str(e.get("role", "trader")),
            }
        logger.info("Loaded %d user(s) from EMSXVIEW_USERS config", len(users))
        return users
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("EMSXVIEW_USERS parse failed (%s) — falling back to DEMO_USERS", exc)
        return {}


_CONFIG_USERS = _load_config_users()
if not _CONFIG_USERS:
    logger.warning(
        "EMSXVIEW_USERS not configured — DEMO_USERS (trader1/trader2/admin, "
        "password='password') remain in effect. Configure EMSXVIEW_USERS "
        "before production use."
    )


# ---------------------------------------------------------------------------
# 动作级授权 (S11/041)：角色 → 允许动作集合
#
# 动作词汇表：
#   trade  — 下单类（路由/建议确认/批量提交/父子单启动与控制/拒绝建议）
#   modify — 修改类（订单/路由修改、撤单、批量更新）
#   admin  — 管理类（路由计划 CRUD、计划应用）
#   view   — 只读（本矩阵只约束写路径；GET 端点维持既有认证门槛）
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: Dict[str, set] = {
    "admin": {"trade", "modify", "admin", "view"},
    "trader": {"trade", "modify", "view"},
    "viewer": {"view"},
}

DEFAULT_PERMISSIONS: set = set()  # 未知角色无任何写权限（fail-closed）


def user_has_permission(user: dict, required: str) -> bool:
    """检查用户角色是否拥有指定动作权限（fail-closed）。"""
    role = str(user.get("role", ""))
    allowed = ROLE_PERMISSIONS.get(role, DEFAULT_PERMISSIONS)
    return required in allowed

class User:
    """User model"""
    def __init__(self, username: str, full_name: str, role: str = "trader"):
        self.username = username
        self.full_name = full_name
        self.role = role
        self.is_active = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "full_name": self.full_name,
            "role": self.role,
            "is_active": self.is_active
        }

class AuthManager:
    """Authentication and authorization manager"""
    
    # Demo users - In production, use database or LDAP/AD integration
    DEMO_USERS = {
        "trader1": {
            "password": "$2b$12$JLMDBJpFqykSN8jD2BahkuJ9OVr5b1h.sAwU7SxN8He5T/1Cj1FXm",  # "password"
            "full_name": "John Smith",
            "role": "trader"
        },
        "trader2": {
            "password": "$2b$12$JLMDBJpFqykSN8jD2BahkuJ9OVr5b1h.sAwU7SxN8He5T/1Cj1FXm",  # "password"
            "full_name": "Jane Doe",
            "role": "trader"
        },
        "admin": {
            "password": "$2b$12$JLMDBJpFqykSN8jD2BahkuJ9OVr5b1h.sAwU7SxN8He5T/1Cj1FXm",  # "password"
            "full_name": "System Admin",
            "role": "admin"
        }
    }
    
    @classmethod
    def verify_password(cls, plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash"""
        return pwd_context.verify(plain_password, hashed_password)
    
    @classmethod
    def get_password_hash(cls, password: str) -> str:
        """Generate password hash"""
        return pwd_context.hash(password)
    
    @classmethod
    def authenticate_user(cls, username: str, password: str) -> Optional[User]:
        """Authenticate user credentials (S10/040, S15/055)。

        用户源语义（第二份审计发现 5 的收紧）：
        - EMSXVIEW_USERS 配置**非空且解析成功** → 配置即权威：未命中的
          用户名一律拒绝（演示账号不再兜底——防止配置正式用户后
          demo 管理员仍可登录）；
        - 配置为空或解析失败 → 回落 DEMO_USERS + 启动 WARNING（开发友好，
          生产部署会看到告警）。
        """
        if _CONFIG_USERS:
            user_data = _CONFIG_USERS.get(username)
        else:
            user_data = cls.DEMO_USERS.get(username)
        if not user_data:
            return None

        if not cls.verify_password(password, user_data["password"]):
            return None

        return User(username, user_data["full_name"], user_data["role"])
    
    @classmethod
    def create_access_token(cls, user: User, expires_delta: Optional[timedelta] = None) -> str:
        """Create JWT access token"""
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
        
        to_encode = {
            "sub": user.username,
            "name": user.full_name,
            "role": user.role,
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": secrets.token_hex(16)  # Unique token ID
        }
        
        return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    @classmethod
    def verify_token(cls, token: str) -> Dict[str, Any]:
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            
            # Check required fields
            username = payload.get("sub")
            if username is None:
                raise HTTPException(401, "Invalid token: missing subject")
            
            # Check if user is authorized
            if ALLOWED_TRADERS and username not in ALLOWED_TRADERS:
                raise HTTPException(403, "User not authorized for trading")
            
            return payload

        except jwt.PyJWTError as e:
            # PyJWT 所有校验异常（过期/签名不符/格式错误）均派生自 PyJWTError
            raise HTTPException(401, f"Invalid or expired token: {str(e)}")
