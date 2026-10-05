import os
import secrets
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import SessionLocal
from app.models import User, Points

load_dotenv()

CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
ALLOWED_IDS = {
    i.strip() for i in os.getenv("ALLOWED_DISCORD_IDS", "").split(",") if i.strip()
}

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


class NotLoggedIn(Exception):
    pass


def get_current_user(request: Request) -> User:
    """Dependency: returns the logged-in User, or sends the browser to /login."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise NotLoggedIn()

    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    db.close()

    if user is None:
        request.session.clear()
        raise NotLoggedIn()
    return user


@router.get("/login")
def login_page(request: Request, error: str = None):
    return templates.TemplateResponse(
        request=request, name="login.html", context={"error": error}
    )


@router.get("/auth/discord")
def auth_discord(request: Request):
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "identify",
        "state": state,
    }
    return RedirectResponse("https://discord.com/oauth2/authorize?" + urlencode(params))


@router.get("/auth/callback")
async def auth_callback(
    request: Request, code: str = None, state: str = None, error: str = None
):
    if error or not code:
        return RedirectResponse("/login?error=Login+was+cancelled.", status_code=303)

    expected_state = request.session.pop("oauth_state", None)
    if not expected_state or not state or not secrets.compare_digest(state, expected_state):
        return RedirectResponse("/login?error=Login+expired.+Please+try+again.", status_code=303)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                "https://discord.com/api/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                auth=(CLIENT_ID, CLIENT_SECRET),
            )
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]

            me_resp = await client.get(
                "https://discord.com/api/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            me_resp.raise_for_status()
            me = me_resp.json()
    except Exception as e:
        print(f"OAUTH ERROR: {type(e).__name__}: {e}")
        return RedirectResponse("/login?error=Discord+login+failed.+Please+try+again.", status_code=303)

    discord_id = str(me["id"])
    display_name = me.get("global_name") or me["username"]
    avatar_hash = me.get("avatar")

    if discord_id not in ALLOWED_IDS:
        return RedirectResponse("/login?error=This+account+isn%27t+on+the+list.", status_code=303)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.discord_id == discord_id).first()
        if user is None:
            user = User(discord_id=discord_id, username=display_name, avatar=avatar_hash)
            db.add(user)
            db.flush()
        else:
            user.username = display_name
            user.avatar = avatar_hash

        if db.query(Points).filter(Points.user_id == user.id).first() is None:
            db.add(Points(user_id=user.id, current_points=0, lifetime_points=0))

        db.commit()
        user_id = user.id
    finally:
        db.close()

    request.session["user_id"] = user_id
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)