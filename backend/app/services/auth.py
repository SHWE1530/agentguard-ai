"""Small, dependency-free authentication.

  * Users come from SENTINEL_USERS ("name:password:role,..."). If unset, two DEMO
    users are used and the login page says so; set SENTINEL_USERS for anything real.
  * Passwords are held only as PBKDF2-HMAC-SHA256 hashes (per-process salt).
  * Tokens are HMAC-SHA256 signed {sub, role, exp}. SENTINEL_SECRET pins the key;
    otherwise a random key is generated, so tokens do not survive a restart.
  * Roles: `operator` may act (start runs, decide approvals, recover);
    `viewer` is read-only. The authenticated name is what gets recorded as the
    human decision-maker, so an approval cannot be attributed to someone else.
  * Failed logins are rate-limited per client (5 in 60 s).

This is deliberately minimal (no SSO, no refresh tokens, no password reset). It
is real enforcement, not a UI gate, but it is not a substitute for an identity
provider in production.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Dict, Optional, Tuple

from backend.app import config

_SALT = secrets.token_bytes(16)
_KEY = (config.AUTH_SECRET or secrets.token_hex(32)).encode()
_attempts: Dict[str, list] = {}


def _hash(pw: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), _SALT, 120_000)


def _load_users() -> Tuple[Dict[str, Tuple[bytes, str]], bool]:
    raw = config.AUTH_USERS or config.DEMO_USERS
    users: Dict[str, Tuple[bytes, str]] = {}
    for item in raw.split(","):
        parts = item.strip().split(":")
        if len(parts) == 3 and parts[2] in ("operator", "viewer"):
            users[parts[0]] = (_hash(parts[1]), parts[2])
    return users, not config.AUTH_USERS


USERS, USING_DEMO_USERS = _load_users()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class RateLimited(Exception):
    pass


def login(name: str, password: str, client: str) -> Optional[dict]:
    now = time.time()
    recent = [t for t in _attempts.get(client, []) if now - t < 60]
    if len(recent) >= 5:
        _attempts[client] = recent
        raise RateLimited()
    entry = USERS.get(name)
    ok = entry is not None and hmac.compare_digest(entry[0], _hash(password))
    if not ok:
        recent.append(now)
        _attempts[client] = recent
        return None
    _attempts.pop(client, None)
    role = entry[1]
    return {"token": issue(name, role), "user": name, "role": role, "expires_in": config.AUTH_TOKEN_TTL_S}


def issue(name: str, role: str) -> str:
    body = _b64(json.dumps({"sub": name, "role": role, "exp": int(time.time()) + config.AUTH_TOKEN_TTL_S}).encode())
    sig = _b64(hmac.new(_KEY, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify(token: str) -> Optional[dict]:
    try:
        body, sig = token.split(".", 1)
        good = _b64(hmac.new(_KEY, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        claims = json.loads(_unb64(body))
        if claims["exp"] < time.time() or claims["sub"] not in USERS:
            return None
        return {"user": claims["sub"], "role": claims["role"]}
    except Exception:
        return None
