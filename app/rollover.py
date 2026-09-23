from datetime import date
from app.database import SessionLocal
from app.models import Habit, DailyCheckin, PointTransaction, Points


def run_daily_rollover(for_date: date = None):
    if for_date is None:
        for_date = date.today()

    db = SessionLocal()
    habits = db.query(Habit).filter(Habit.active == True).all()
    points_row = db.query(Points).first()

    total_earned = 0

    for habit in habits:
        checkin = db.query(DailyCheckin).filter(
            DailyCheckin.habit_id == habit.id,
            DailyCheckin.date == for_date
        ).first()

        completed = checkin.completed if checkin else False

        failed = (
            (habit.type == "good" and completed == False)
            or (habit.type == "bad" and completed == True)
        )

        if failed:
            transaction = PointTransaction(
                amount=habit.point_value,
                type="failure",
                reason=f"Missed {habit.name}" if habit.type == "good" else f"Did {habit.name}",
            )
            db.add(transaction)
            total_earned += habit.point_value

    points_row.current_points += total_earned
    points_row.lifetime_points += total_earned

    db.commit()
    db.close()