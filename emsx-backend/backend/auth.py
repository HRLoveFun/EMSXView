#!/usr/bin/env python3
"""
EMSX Trading API - Authentication Module
Handles user authentication and authorization
"""

import os
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from functools import wraps

from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
ALLOWED_TRADERS = [t.strip() for t in os.getenv("ALLOWED_TRADERS", "").split(",") if t.strip()]

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
        """Authenticate user credentials"""
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
            
        except JWTError as e:
            raise HTTPException(401, f"Invalid or expired token: {str(e)}")
    
    @classmethod
    def require_role(cls, roles: List[str]):
        """Decorator to require specific role"""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                user = kwargs.get('user')
                if not user or user.get('role') not in roles:
                    raise HTTPException(403, "Insufficient permissions")
                return await func(*args, **kwargs)
            return wrapper
        return decorator

# FastAPI dependency
async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    """FastAPI dependency to get current authenticated user"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return AuthManager.verify_token(credentials.credentials)

def audit_log(action: str, user: str, details: Dict[str, Any]):
    """Log audit trail"""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "user": user,
        "details": details
    }
    
    # In production, write to secure audit log database
    print(f"[AUDIT] {json.dumps(log_entry)}")

# API Key authentication (for service-to-service)
API_KEYS = {
    "emsx-frontend": os.getenv("FRONTEND_API_KEY", secrets.token_urlsafe(32))
}

def verify_api_key(api_key: str) -> bool:
    """Verify service API key"""
    return api_key in API_KEYS.values()
