from datetime import date
from app.database import SessionLocal
from app.models import Habit, DailyCheckin, PointTransaction, Points


def run_daily_rollover(for_date: date = None):
    if for_date is None:
        for_date = date.today()

    db = SessionLocal()
    points_row = db.query(Points).first()

    if points_row.last_rollover_date == for_date:
        db.close()
        return

    habits = db.query(Habit).filter(Habit.active == True, Habit.type == "good").all()

    total_earned = 0

    for habit in habits:
        checkin = db.query(DailyCheckin).filter(
            DailyCheckin.habit_id == habit.id,
            DailyCheckin.date == for_date
        ).first()

        completed = checkin.completed if checkin else False

        if not completed:
            transaction = PointTransaction(
                amount=habit.point_value,
                type="failure",
                reason=f"Missed {habit.name}",
            )
            db.add(transaction)
            total_earned += habit.point_value

    points_row.current_points += total_earned
    points_row.lifetime_points += total_earned
    points_row.last_rollover_date = for_date

    db.commit()
    db.close()