"""Small token-to-cookie login for native browser media clients.

The token is entered in a password form, never embedded in assets or URLs.
Sessions are stateless, expire after eight hours and are revoked by token rotation.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()
COOKIE_NAME = "medfire_session"
SESSION_SECONDS = 8 * 3600


def valid_token(value: str, token: str) -> bool:
    return bool(token and value) and secrets.compare_digest(value.encode(), token.encode())


def _signature(payload: str, token: str) -> str:
    return hmac.new(token.encode(), ("browser-session:" + payload).encode(), hashlib.sha256).hexdigest()


def valid_session(value: str, token: str) -> bool:
    if not token or len(value) > 256:
        return False
    try:
        expires, nonce, signature = value.split(".")
        remaining = int(expires) - time.time()
        return 0 < remaining <= SESSION_SECONDS and secrets.compare_digest(
            signature, _signature(f"{expires}.{nonce}", token)
        )
    except (ValueError, TypeError):
        return False


def _destination(value: str) -> str:
    return value if value in {"/live-camera", "/video-test"} else "/live-camera"


@router.get("/auth/login", response_class=HTMLResponse)
def login_page(next: str = "/live-camera", error: bool = False) -> HTMLResponse:
    destination = html.escape(_destination(next), quote=True)
    message = "Invalid API token. Try again." if error else "Enter the API token configured by the operator."
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>MedFire Watch sign in</title>'
        '<body style="background:#07101b;color:#f2f7fb;font:18px system-ui;padding:2rem">'
        '<h1>MedFire Watch</h1><p role="status">' + message + "</p>"
        '<form method="post" action="/auth/session"><label for="token">API token</label> '
        '<input id="token" name="token" type="password" maxlength="4096" required autocomplete="current-password">'
        f'<input type="hidden" name="next" value="{destination}"> '
        '<button type="submit">Sign in</button></form><p>The session expires after eight hours.</p></body></html>',
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/auth/session")
def create_session(request: Request, token: str = Form(max_length=4096), next: str = Form("/live-camera")):
    configured = os.getenv("MEDFIRE_API_TOKEN", "").strip()
    destination = _destination(next)
    if not valid_token(token, configured):
        return RedirectResponse(f"/auth/login?next={destination}&error=true", status_code=303)
    payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(16)}"
    response = RedirectResponse(destination, status_code=303, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        COOKIE_NAME,
        f"{payload}.{_signature(payload, configured)}",
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return response


@router.post("/auth/logout")
def logout():
    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    return response
