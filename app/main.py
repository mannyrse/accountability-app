import os
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from app.database import SessionLocal
from app.models import Habit, DailyCheckin, Points, PointTransaction, Reward, PendingNotification, Redemption, User
from app.auth import router as auth_router, NotLoggedIn, get_current_user
from datetime import date, timedelta, datetime, timezone
from app.rollover import run_daily_rollover
from apscheduler.schedulers.background import BackgroundScheduler
from typing import Optional
from contextlib import asynccontextmanager
import asyncio
from bot.bot import bot, TOKEN
from fastapi.staticfiles import StaticFiles
from apscheduler.triggers.cron import CronTrigger
import pytz
from fastapi.responses import JSONResponse
from app.timezone_utils import eastern_today
from sqlalchemy import func
from urllib.parse import quote


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(bot.start(TOKEN))
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET"),
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=bool(os.getenv("RENDER")),
)
app.include_router(auth_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.exception_handler(NotLoggedIn)
async def not_logged_in_handler(request: Request, exc: NotLoggedIn):
    return RedirectResponse(url="/login", status_code=303)


def to_eastern(dt):
    # DB stores naive UTC datetimes; convert to Eastern for display
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(pytz.timezone("America/New_York"))


templates.env.filters["eastern"] = to_eastern
def avatar_url(discord_id: str, avatar_hash: Optional[str]) -> str:
    if avatar_hash:
        return f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png?size=64"
    # No custom avatar: Discord's default one, picked by account ID
    return f"https://cdn.discordapp.com/embed/avatars/{(int(discord_id) >> 22) % 6}.png"


templates.env.globals["avatar_url"] = avatar_url


# Helpers

VALID_HABIT_TYPES = ("good", "bad", "virtue")
MAX_ACTIVE_VIRTUES = 3


def clamp_virtue_points(value: int) -> int:
    return max(1, min(3, value))


def active_virtue_count(db, user: User) -> int:
    return db.query(Habit).filter(
        Habit.user_id == user.id, Habit.type == "virtue", Habit.active == True
    ).count()


def get_owned(db, model, item_id, user: User):
    """Fetch a row only if it belongs to this user; otherwise 404 (and close the session)."""
    item = db.query(model).filter(model.id == item_id, model.user_id == user.id).first()
    if item is None:
        db.close()
        raise HTTPException(status_code=404, detail="Not found")
    return item


def get_points(db, user: User) -> Points:
    row = db.query(Points).filter(Points.user_id == user.id).first()
    if row is None:
        row = Points(user_id=user.id, current_points=0, lifetime_points=0)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@app.post("/add-habit")
def create_habit(
    name: str = Form(...),
    type: str = Form(...),
    point_value: int = Form(1),
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    if type not in VALID_HABIT_TYPES:
        db.close()
        return RedirectResponse(url="/", status_code=303)

    point_value = max(1, point_value)
    if type == "virtue":
        if active_virtue_count(db, user) >= MAX_ACTIVE_VIRTUES:
            db.close()
            return RedirectResponse(url="/", status_code=303)
        point_value = clamp_virtue_points(point_value)

    new_habit = Habit(user_id=user.id, name=name, type=type, point_value=point_value)
    db.add(new_habit)
    db.commit()
    db.close()
    return RedirectResponse(url="/", status_code=303)


@app.get("/")
def show_checklist(
    request: Request,
    edit_id: Optional[int] = None,
    add_type: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    points_row = get_points(db, user)

    habits = db.query(Habit).filter(Habit.user_id == user.id, Habit.active == True).all()

    today = eastern_today()
    checklist = []
    for habit in habits:
        checkin = db.query(DailyCheckin).filter(
            DailyCheckin.habit_id == habit.id,
            DailyCheckin.date == today
        ).first()
        is_checked = checkin.completed if checkin else False
        checklist.append({"habit": habit, "checked": is_checked})

    editing_habit = None
    if edit_id is not None:
        editing_habit = db.query(Habit).filter(Habit.id == edit_id, Habit.user_id == user.id).first()

    db.close()
    return templates.TemplateResponse(
        request=request, name="checklist.html",
        context={
            "checklist": checklist,
            "editing_habit": editing_habit,
            "add_type": add_type,
            "points": points_row,
            "user": user,
            "today": today.strftime("%A, %B %-d"),
        }
    )


@app.get("/delete-habit/{habit_id}")
def delete_habit(habit_id: int, user: User = Depends(get_current_user)):
    db = SessionLocal()
    habit = get_owned(db, Habit, habit_id, user)
    habit.active = False
    db.commit()
    db.close()
    return RedirectResponse(url="/", status_code=303)


@app.post("/edit-habit/{habit_id}")
def edit_habit(
    habit_id: int,
    name: str = Form(...),
    type: str = Form(...),
    point_value: int = Form(1),
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    habit = get_owned(db, Habit, habit_id, user)

    if type not in VALID_HABIT_TYPES:
        db.close()
        return RedirectResponse(url="/", status_code=303)

    point_value = max(1, point_value)
    if type == "virtue":
        # Don't allow converting a habit into a 4th virtue.
        if habit.type != "virtue" and active_virtue_count(db, user) >= MAX_ACTIVE_VIRTUES:
            db.close()
            return RedirectResponse(url="/", status_code=303)
        point_value = clamp_virtue_points(point_value)

    habit.name = name
    habit.type = type
    habit.point_value = point_value
    db.commit()
    db.close()
    return RedirectResponse(url="/", status_code=303)


@app.post("/add-reward")
def create_reward(
    name: str = Form(...),
    description: str = Form(""),
    point_cost: int = Form(...),
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    new_reward = Reward(
        user_id=user.id, name=name, description=description, point_cost=max(1, point_cost)
    )
    db.add(new_reward)
    db.commit()
    db.close()
    return RedirectResponse(url="/rewards", status_code=303)


@app.get("/delete-reward/{reward_id}")
def delete_reward(reward_id: int, user: User = Depends(get_current_user)):
    db = SessionLocal()
    reward = get_owned(db, Reward, reward_id, user)
    reward.active = False
    db.commit()
    db.close()
    return RedirectResponse(url="/rewards", status_code=303)


@app.post("/edit-reward/{reward_id}")
def edit_reward(
    reward_id: int,
    name: str = Form(...),
    description: str = Form(""),
    point_cost: int = Form(...),
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    reward = get_owned(db, Reward, reward_id, user)
    reward.name = name
    reward.description = description
    reward.point_cost = max(1, point_cost)
    db.commit()
    db.close()
    return RedirectResponse(url="/rewards", status_code=303)


@app.get("/rewards")
def show_rewards(
    request: Request,
    add_reward: Optional[bool] = None,
    edit_reward_id: Optional[int] = None,
    user: User = Depends(get_current_user),
):
    db = SessionLocal()
    points_row = get_points(db, user)
    shops = [
        {"id": u.id, "name": u.username, "avatar": avatar_url(u.discord_id, u.avatar)}
        for u in db.query(User).filter(User.id != user.id).order_by(User.username).all()
    ]

    rewards = (
        db.query(Reward)
        .filter(Reward.user_id == user.id, Reward.active == True)
        .order_by(Reward.point_cost.asc())
        .all()
    )
    redemptions = (
        db.query(Redemption)
        .filter(Redemption.user_id == user.id)
        .order_by(Redemption.redeemed_at.desc())
        .limit(30)
        .all()
    )
    gamble_rows = (
        db.query(PointTransaction)
        .filter(PointTransaction.user_id == user.id, PointTransaction.type == "gamble")
        .order_by(PointTransaction.created_at.desc())
        .limit(5)
        .all()
    )
    gambles = []
    for g in gamble_rows:
        # Everything that changed this user's points after this gamble
        newer = db.query(func.coalesce(func.sum(PointTransaction.amount), 0)).filter(
            PointTransaction.user_id == user.id,
            PointTransaction.created_at > g.created_at,
        ).scalar()
        gambles.append({
            "amount": g.amount,
            "balance_after": points_row.current_points - newer,
        })

    editing_reward = None
    if edit_reward_id is not None:
        editing_reward = db.query(Reward).filter(
            Reward.id == edit_reward_id, Reward.user_id == user.id
        ).first()

    db.close()
    return templates.TemplateResponse(
        request=request, name="rewards.html",
        context={
            "rewards": rewards,
            "points": points_row,
            "add_reward": add_reward,
            "editing_reward": editing_reward,
            "redemptions": redemptions,
            "shops": shops,
            "gambles": gambles,
            "user": user,
            "today": eastern_today().strftime("%A, %B %-d"),
        }
    )


@app.get("/toggle-redemption/{redemption_id}")
def toggle_redemption(redemption_id: int, user: User = Depends(get_current_user)):
    db = SessionLocal()
    redemption = get_owned(db, Redemption, redemption_id, user)
    redemption.completed = not redemption.completed
    if not redemption.completed:
        redemption.completion_announced = False
    db.commit()
    db.close()
    return RedirectResponse(url="/rewards", status_code=303)


@app.post("/toggle-checkin")
async def toggle_checkin(request: Request, user: User = Depends(get_current_user)):
    data = await request.json()
    habit_id = data.get("habit_id")
    was_checked = data.get("checked")

    db = SessionLocal()
    habit = get_owned(db, Habit, habit_id, user)
    today = eastern_today()
    points_row = get_points(db, user)

    checkin = db.query(DailyCheckin).filter(
        DailyCheckin.habit_id == habit.id,
        DailyCheckin.date == today
    ).first()

    if not checkin:
        checkin = DailyCheckin(habit_id=habit.id, date=today, completed=was_checked)
        db.add(checkin)
        db.flush()
    else:
        checkin.completed = was_checked

    if habit.type == "bad":
        if was_checked and not checkin.point_awarded:
            transaction = PointTransaction(
                user_id=user.id,
                amount=habit.point_value,
                type="failure",
                reason=f"Did {habit.name}",
            )
            db.add(transaction)
            db.flush()
            checkin.point_awarded = True
            checkin.point_transaction_id = transaction.id
            points_row.current_points += habit.point_value
            points_row.lifetime_points += habit.point_value

            existing_notification = db.query(PendingNotification).filter(
                PendingNotification.habit_id == habit.id,
                PendingNotification.date == today,
            ).first()
            if existing_notification:
                existing_notification.status = "pending"
                existing_notification.scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=1)
            else:
                notification = PendingNotification(
                    habit_id=habit.id,
                    date=today,
                    scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=1),
                    status="pending",
                )
                db.add(notification)

        elif not was_checked and checkin.point_awarded:
            old_transaction = db.query(PointTransaction).filter(
                PointTransaction.id == checkin.point_transaction_id
            ).first()
            if old_transaction:
                points_row.current_points = max(0, points_row.current_points - old_transaction.amount)
                points_row.lifetime_points -= old_transaction.amount
                db.delete(old_transaction)
            checkin.point_awarded = False
            checkin.point_transaction_id = None

            pending = db.query(PendingNotification).filter(
                PendingNotification.habit_id == habit.id,
                PendingNotification.date == today,
                PendingNotification.status == "pending",
            ).first()
            if pending:
                pending.status = "cancelled"

    elif habit.type == "virtue":
        if was_checked and not checkin.point_awarded:
            # Subtract, but never below zero. Only log what was actually removed.
            deducted = min(habit.point_value, max(points_row.current_points, 0))
            if deducted > 0:
                transaction = PointTransaction(
                    user_id=user.id,
                    amount=-deducted,
                    type="virtue",
                    reason=f"Virtue: {habit.name}",
                )
                db.add(transaction)
                db.flush()
                checkin.point_awarded = True
                checkin.point_transaction_id = transaction.id
                points_row.current_points -= deducted
                # lifetime_points is untouched: it only ever increases.

        elif not was_checked and checkin.point_awarded:
            # Reverse exactly what THIS checkin removed (read from its own
            # transaction), never the habit's current point_value.
            old_transaction = db.query(PointTransaction).filter(
                PointTransaction.id == checkin.point_transaction_id
            ).first()
            checkin.point_awarded = False
            checkin.point_transaction_id = None
            if old_transaction:
                points_row.current_points += -old_transaction.amount
                db.delete(old_transaction)

    db.commit()
    current = points_row.current_points
    lifetime = points_row.lifetime_points
    db.close()

    return JSONResponse({"current_points": current, "lifetime_points": lifetime})

@app.get("/friends")
def show_friends(request: Request, user: User = Depends(get_current_user)):
    db = SessionLocal()
    today = eastern_today()

    rows = db.query(User, Points).outerjoin(Points, Points.user_id == User.id).all()

    habits = db.query(Habit).filter(Habit.active == True).order_by(Habit.id).all()
    checked_ids = {
        c.habit_id
        for c in db.query(DailyCheckin).filter(
            DailyCheckin.date == today, DailyCheckin.completed == True
        ).all()
    }
    habits_by_user = {}
    for h in habits:
        groups = habits_by_user.setdefault(h.user_id, {"good": [], "bad": [], "virtue": []})
        if h.type in groups:
            groups[h.type].append({
                "name": h.name,
                "points": h.point_value,
                "checked": h.id in checked_ids,
            })

    friends = [
        {
            "name": u.username,
            "avatar": avatar_url(u.discord_id, u.avatar),
            "current": p.current_points if p else 0,
            "lifetime": p.lifetime_points if p else 0,
            "is_me": u.id == user.id,
            "habits": habits_by_user.get(u.id, {"good": [], "bad": [], "virtue": []}),
        }
        for u, p in rows
    ]
    db.close()

    # Fewest points first, since fewer is better
    friends.sort(key=lambda f: (f["current"], f["lifetime"], f["name"].lower()))

    return templates.TemplateResponse(
        request=request, name="friends.html",
        context={
            "friends": friends,
            "user": user,
            "today": eastern_today().strftime("%A, %B %-d"),
        }
    )

@app.get("/shop/{owner_id}")
def show_shop(
    request: Request,
    owner_id: int,
    redeemed: Optional[str] = None,
    error: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    if owner_id == user.id:
        return RedirectResponse(url="/rewards", status_code=303)

    db = SessionLocal()
    owner = db.query(User).filter(User.id == owner_id).first()
    if owner is None:
        db.close()
        raise HTTPException(status_code=404, detail="Not found")

    points_row = db.query(Points).filter(Points.user_id == owner.id).first()
    owner_points = points_row.current_points if points_row else 0

    rewards = [
        {"id": r.id, "name": r.name, "description": r.description, "cost": r.point_cost}
        for r in db.query(Reward)
        .filter(Reward.user_id == owner.id, Reward.active == True)
        .order_by(Reward.point_cost.asc())
        .all()
    ]
    shops = [
        {"id": u.id, "name": u.username, "avatar": avatar_url(u.discord_id, u.avatar)}
        for u in db.query(User).filter(User.id != user.id).order_by(User.username).all()
    ]
    owner_info = {
        "id": owner.id,
        "name": owner.username,
        "avatar": avatar_url(owner.discord_id, owner.avatar),
        "points": owner_points,
    }
    db.close()

    return templates.TemplateResponse(
        request=request, name="shop.html",
        context={
            "owner": owner_info,
            "rewards": rewards,
            "shops": shops,
            "redeemed": redeemed,
            "error": error,
            "user": user,
            "today": eastern_today().strftime("%A, %B %-d"),
        },
    )


@app.post("/shop/{owner_id}/redeem/{reward_id}")
def redeem_from_friend(owner_id: int, reward_id: int, user: User = Depends(get_current_user)):
    if owner_id == user.id:
        return RedirectResponse(url="/rewards", status_code=303)

    db = SessionLocal()
    owner = db.query(User).filter(User.id == owner_id).first()
    if owner is None:
        db.close()
        raise HTTPException(status_code=404, detail="Not found")

    reward = db.query(Reward).filter(
        Reward.id == reward_id, Reward.user_id == owner.id, Reward.active == True
    ).first()
    if reward is None:
        db.close()
        return RedirectResponse(
            url=f"/shop/{owner_id}?error={quote('That reward is no longer available.')}",
            status_code=303,
        )

    points_row = get_points(db, owner)
    if points_row.current_points < reward.point_cost:
        message = f"{owner.username} only has {points_row.current_points} points, but {reward.name} costs {reward.point_cost}."
        db.close()
        return RedirectResponse(url=f"/shop/{owner_id}?error={quote(message)}", status_code=303)

    reward_name = reward.name
    cost = reward.point_cost

    db.add(PointTransaction(
        user_id=owner.id,
        amount=-cost,
        type="reward",
        reason=f"{reward_name} (redeemed by {user.username})",
    ))
    points_row.current_points -= cost

    db.add(Redemption(
        user_id=owner.id,
        reward_name=reward_name,
        point_cost=cost,
        completed=False,
        redeemed_by_discord_id=user.discord_id,
        redeemed_by_name=user.username,
        redeem_announced=False,
    ))
    db.commit()
    db.close()

    return RedirectResponse(url=f"/shop/{owner_id}?redeemed={quote(reward_name)}", status_code=303)

@app.get("/health")
def health_check():
    return {"status": "ok"}


scheduler = BackgroundScheduler()
scheduler.add_job(
    run_daily_rollover,
    CronTrigger(hour=23, minute=59, timezone=pytz.timezone("America/New_York"))
)
scheduler.start()