"""Cookie-based local registration and login; credentials never appear in responses."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ._schemas import Credentials, project
from .config import settings
from .db import get_db
from .models import User
from .security import (
    COOKIE_NAME,
    current_user,
    end_session,
    hash_password,
    start_session,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
_DUMMY_HASH = hash_password("non-account timing placeholder")


@router.post("/register")
def register(
    data: Credentials, request: Request, response: Response, db: Session = Depends(get_db)
):
    """Create an account and session; duplicate normalized email returns 409."""
    user = User(email=data.email, password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.flush()
        start_session(db, user, request, response)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from None
    return project(user, "id email")


@router.post("/login")
def login(data: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    """Authenticate and rotate the session; wrong credentials return a generic 401."""
    user = db.scalar(select(User).where(User.email == data.email))
    valid = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not valid:
        raise HTTPException(401, "Email or password is incorrect")
    start_session(db, user, request, response)
    db.commit()
    return project(user, "id email")


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Revoke any current session and clear the browser cookie, idempotently."""
    end_session(db, request)
    db.commit()
    response.delete_cookie(
        COOKIE_NAME, path="/", httponly=True, secure=settings.cookie_secure, samesite="strict"
    )
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    """Return only the authenticated user's public identity."""
    return project(user, "id email")
