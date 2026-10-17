"""Admin panel routes for dashboard, scraper, and system monitoring."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from server import config as server_config
from server import deps as server_deps
from server.auth.security import create_access_token, verify_password
from server.database.mobile_models import User
from server.schemas.auth import AuthResponse, LoginRequest, UserOut
from server.services import admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login", response_model=AuthResponse)
def admin_login(body: LoginRequest, db: Session = Depends(server_deps.get_mobile_db)) -> AuthResponse:
    email = body.email.lower()
    allowed_admins = {value.lower() for value in server_config.ADMIN_EMAILS}
    if not allowed_admins:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access is not configured on this server.",
        )
    if email not in allowed_admins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")

    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None or not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")

    token, expires_in = create_access_token(user.id)
    return AuthResponse(token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.get("/dashboard")
def dashboard(current_user: User = Depends(server_deps.require_admin)):
    return admin_service.get_dashboard_summary()


@router.get("/scraper/status")
def scraper_status(current_user: User = Depends(server_deps.require_admin)):
    return admin_service.get_scraper_status()


@router.get("/system")
def system_status(current_user: User = Depends(server_deps.require_admin)):
    return admin_service.get_system_status()
