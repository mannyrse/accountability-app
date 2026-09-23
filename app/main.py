from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from app.database import SessionLocal
from app.models import Habit, DailyCheckin
from datetime import date

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

@app.get("/add-habit")
def show_add_habit_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="add_habit.html"
    )

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
def show_checklist(request: Request):
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

    db.close()
    return templates.TemplateResponse(
        request=request, name="checklist.html", context={"checklist": checklist}
    )