"""Owner-only authorization and expiring sessions; foreign IDs always return 404."""

import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from .config import settings
from .db import get_db, utcnow
from .models import Company, Machine, Session, Source, User

COOKIE_NAME = "newton_session"
SESSION_SECONDS = 7 * 24 * 60 * 60


def hash_password(password: str) -> str:
    """Hash a password using a fresh salt and bounded stdlib scrypt parameters."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Compare password hashes in constant time, rejecting malformed stored hashes."""
    try:
        scheme, salt, expected = encoded.split("$")
        if scheme != "scrypt" or len(salt) != 32 or len(expected) != 64:
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except ValueError, TypeError:
        return False


def token_hash(token: str) -> str:
    """Return the irreversible database identifier for a session cookie."""
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: DBSession, user: User, request: Request, response: Response) -> None:
    """Rotate the browser's login and set an expiring, HttpOnly, strict cookie."""
    end_session(db, request)
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(seconds=SESSION_SECONDS)
    db.add(Session(id=token_hash(token), user_id=user.id, expires_at=expires))
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        expires=expires,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def end_session(db: DBSession, request: Request) -> None:
    """Revoke the supplied session if it exists; caller commits the transaction."""
    token = request.cookies.get(COOKIE_NAME, "")
    if token and len(token) <= 200:
        session = db.get(Session, token_hash(token))
        if session:
            db.delete(session)


def current_user(request: Request, db: DBSession = Depends(get_db)) -> User:
    """Return the active account or raise 401 for absent, revoked or expired cookies."""
    token = request.cookies.get(COOKIE_NAME, "")
    session = db.get(Session, token_hash(token)) if token and len(token) <= 200 else None
    if session is None or session.expires_at <= utcnow():
        raise HTTPException(401, "Sign in to continue")
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(401, "Sign in to continue")
    return user


def lock_current_session(request: Request, db: DBSession) -> User:
    """Serialize answer acceptance with logout, then validate session expiry.

    The caller holds its investigation/machine locks first. Logout only locks
    the session, so there is no opposite machine-to-session lock dependency.
    """
    token = request.cookies.get(COOKIE_NAME, "")
    session = db.scalar(
        select(Session)
        .where(Session.id == token_hash(token))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is None:
        raise HTTPException(401, "Sign in to continue")
    return current_user(request, db)


def require_company(db: DBSession, user: User, company_id: str) -> Company:
    """Return a company owned by this user, hiding unknown and foreign IDs with 404."""
    company = db.scalar(
        select(Company).where(Company.id == company_id, Company.owner_id == user.id)
    )
    if company is None:
        raise HTTPException(404, "Company not found")
    return company


def require_machine(db: DBSession, user: User, machine_id: str) -> Machine:
    """Authorize machine traversal via its persisted company, never a client company ID."""
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(404, "Machine not found")
    require_company(db, user, machine.company_id)
    return machine


def require_source(db: DBSession, user: User, source_id: str) -> Source:
    """Authorize every source traversal through both its stored company and machine."""
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    require_company(db, user, source.company_id)
    machine = require_machine(db, user, source.machine_id) if source.machine_id else None
    if machine is not None and machine.company_id != source.company_id:
        raise HTTPException(404, "Source not found")
    return source
