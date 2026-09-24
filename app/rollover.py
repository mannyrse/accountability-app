from datetime import date
from app.database import SessionLocal
from app.models import Habit, DailyCheckin, PointTransaction, Points, DailyReport


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
    missed_habits = []

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
            missed_habits.append(habit.name)

    points_row.current_points += total_earned
    points_row.lifetime_points += total_earned
    points_row.last_rollover_date = for_date

    if missed_habits:
        missed_list = "\n".join(f"❌ {name}" for name in missed_habits)
        message = f"📋 Daily Report ({for_date})\n\n{missed_list}\n\nPoints earned: +{total_earned}\nCurrent points: {points_row.current_points}\nLifetime points: {points_row.lifetime_points}"
    else:
        message = f"📋 Daily Report ({for_date})\n\nAll good habits completed! 🎉\n\nCurrent points: {points_row.current_points}\nLifetime points: {points_row.lifetime_points}"

    report = DailyReport(date=for_date, message=message, status="pending")
    db.add(report)

    db.commit()
    db.close()