from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from app.database import SessionLocal
from app.models import Habit, DailyCheckin, Points, PointTransaction, Reward, PendingNotification
from datetime import date, timedelta, datetime, timezone
from app.rollover import run_daily_rollover
from apscheduler.schedulers.background import BackgroundScheduler
from typing import Optional

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")


@app.post("/add-habit")
def create_habit(
    name: str = Form(...),
    type: str = Form(...),
    point_value: int = Form(1),
):
    db = SessionLocal()
    new_habit = Habit(name=name, type=type, point_value=point_value)
    db.add(new_habit)
    db.commit()
    db.close()
    return RedirectResponse(url="/", status_code=303)


@app.get("/")
def show_checklist(request: Request, edit_id: Optional[int] = None, add_type: Optional[str] = None):
    db = SessionLocal()
    habits = db.query(Habit).filter(Habit.active == True).all()

    today = date.today()
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
        editing_habit = db.query(Habit).filter(Habit.id == edit_id).first()

    points_row = db.query(Points).first()

    db.close()
    return templates.TemplateResponse(
        request=request, name="checklist.html",
        context={
            "checklist": checklist,
            "editing_habit": editing_habit,
            "add_type": add_type,
            "points": points_row,
        }
    )


@app.get("/delete-habit/{habit_id}")
def delete_habit(habit_id: int):
    db = SessionLocal()
    habit = db.query(Habit).filter(Habit.id == habit_id).first()
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
):
    db = SessionLocal()
    habit = db.query(Habit).filter(Habit.id == habit_id).first()
    habit.name = name
    habit.type = type
    habit.point_value = point_value
    db.commit()
    db.close()
    return RedirectResponse(url="/", status_code=303)


@app.post("/save-checklist")
async def save_checklist(request: Request):
    form_data = await request.form()
    db = SessionLocal()

    habits = db.query(Habit).filter(Habit.active == True).all()
    today = date.today()
    points_row = db.query(Points).first()

    for habit in habits:
        field_name = f"habit_{habit.id}"
        was_checked = field_name in form_data

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

                existing_nofication = db.query(PendingNotification).filter(
                    PendingNotification.habit_id == habit.id,
                    PendingNotification.date == today,
                ).first()

                if existing_nofication:
                    existing_nofication.status = "pending"
                    existing_nofication.scheduled_at = datetime.now(timezone.utc)
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
                    points_row.current_points -= old_transaction.amount
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

    db.commit()
    db.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/add-reward")
def create_reward(
    name: str = Form(...),
    description: str = Form(""),
    point_cost: int = Form(...),
):
    db = SessionLocal()
    new_reward  = Reward(name=name, description=description, point_cost=point_cost)
    db.add(new_reward)
    db.commit()
    db.close()
    return RedirectResponse(url="/rewards", status_code=303)

@app.get("/rewards")
def show_rewards(request: Request, add_reward: Optional[bool] = None):
    db = SessionLocal()
    rewards = db.query(Reward).filter(Reward.active == True).all()
    points_row = db.query(Points).first()
    db.close()
    return templates.TemplateResponse(
        request=request, name="rewards.html",
        context={"rewards": rewards, "points": points_row, "add_reward": add_reward}
    )

@app.post("/redeem/{reward_id}")
def redeem_reward(reward_id: int):
    db = SessionLocal()
    reward = db.query(Reward).filter(Reward.id == reward_id).first()
    points_row = db.query(Points).first()

    if points_row.current_points >= reward.point_cost:
        transaction = PointTransaction(
            amount=-reward.point_cost,
            type="reward",
            reason=reward.name,
        )
        db.add(transaction)
        points_row.current_points -= reward.point_cost

    db.commit()
    db.close()
    return RedirectResponse(url="/rewards", status_code=303)

@app.get("/test-rollover")
def test_rollover():
    run_daily_rollover()
    return {"status": "rollover ran"}


scheduler = BackgroundScheduler()
scheduler.add_job(run_daily_rollover, "cron", hour=23, minute=59)
scheduler.start()