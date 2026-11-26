from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..notify.dispatch import prefs_of
from ..schemas import LoginIn, PasswordIn, ProfileIn
from ..security import (
    COOKIE,
    check_credentials,
    current_user,
    hash_password,
    limiter,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/api", tags=["conta"])


def user_dict(user: User) -> dict:
    return {
        "id": user.id, "username": user.username, "is_admin": user.is_admin, "email": user.email,
        "whatsapp": user.whatsapp, "callmebot_key": user.callmebot_key, "prefs": prefs_of(user),
    }


@router.post("/auth/login")
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    keys = (f"ip:{ip}", f"user:{ip}:{data.username.lower()}")
    limiter.check(*keys)
    user = check_credentials(db, data.username, data.password)
    if user is None:
        limiter.fail(*keys)
        raise HTTPException(401, "Usuário ou senha incorretos")
    limiter.reset(*keys)
    set_session_cookie(response, request, user)
    return user_dict(user)


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_dict(user)


@router.put("/me")
def update_me(
    data: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    user.email, user.whatsapp = data.email, data.whatsapp
    user.callmebot_key = data.callmebot_key.strip()
    user.prefs = data.prefs.model_dump()
    db.commit()
    return user_dict(user)


@router.post("/me/password")
def change_password(
    data: PasswordIn, request: Request, response: Response,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    key = f"pw:{user.id}"
    limiter.check(key)
    if not verify_password(data.current, user.password_hash):
        limiter.fail(key)
        raise HTTPException(400, "Senha atual incorreta")
    user.password_hash = hash_password(data.new)
    user.token_version += 1  # encerra as outras sessões
    db.commit()
    set_session_cookie(response, request, user)
    return {"ok": True}
