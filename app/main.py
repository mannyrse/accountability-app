from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from app.database import SessionLocal
from app.models import Habit, DailyCheckin
from datetime import date
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

    db.close()
    return templates.TemplateResponse(
        request=request, name="checklist.html",
        context={"checklist": checklist, "editing_habit": editing_habit, "add_type": add_type}
    )


@app.post("/save-checklist")
async def save_checklist(request: Request):
    form_data = await request.form()
    db = SessionLocal()

    habits = db.query(Habit).filter(Habit.active == True).all()
    today = date.today()

    for habit in habits:
        field_name = f"habit_{habit.id}"
        was_checked = field_name in form_data

        checkin = db.query(DailyCheckin).filter(
            DailyCheckin.habit_id == habit.id,
            DailyCheckin.date == today
        ).first()

        if checkin:
            checkin.completed = was_checked
        else:
            checkin = DailyCheckin(habit_id=habit.id, date=today, completed=was_checked)
            db.add(checkin)

    db.commit()
    db.close()
    return RedirectResponse(url="/", status_code=303)


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


@app.get("/test-rollover")
def test_rollover():
    run_daily_rollover()
    return {"status": "rollover ran"}


scheduler = BackgroundScheduler()
scheduler.add_job(run_daily_rollover, "cron", hour=23, minute=59)
scheduler.start()