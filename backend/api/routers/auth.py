"""Auth domain router — /api/auth/* endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from schemas import ApiResponse, LoginRequest
from auth import AuthManager

router = APIRouter(tags=["Auth"])


@router.post("/api/auth/login", response_model=ApiResponse)
async def login(request: LoginRequest):
    """Authenticate user and return JWT access token."""
    user = AuthManager.authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = AuthManager.create_access_token(user)
    return ApiResponse(
        success=True,
        data={"token": token, "user": user.to_dict()},
        message="Login successful",
    )
