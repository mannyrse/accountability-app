from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from app.database import SessionLocal
from app.models import Habit

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
    return RedirectResponse(url="/add-habit", status_code=303)
