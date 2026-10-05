from datetime import date
from app.database import SessionLocal
from app.models import Habit, DailyCheckin, PointTransaction, Points, DailyReport, User
from app.timezone_utils import eastern_today


def _get_points_row(db, user: User) -> Points:
    row = db.query(Points).filter(Points.user_id == user.id).first()
    if row is None:
        row = Points(user_id=user.id, current_points=0, lifetime_points=0)
        db.add(row)
        db.flush()
    return row


def run_daily_rollover(for_date: date = None):
    if for_date is None:
        for_date = eastern_today()

    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id).all()
        blocks = []

        for user in users:
            points_row = _get_points_row(db, user)

            # Idempotent per person: skip anyone already scored for this day
            if points_row.last_rollover_date == for_date:
                continue

            habits = db.query(Habit).filter(
                Habit.user_id == user.id,
                Habit.active == True,
                Habit.type == "good",
            ).all()

            total_earned = 0
            missed_habits = []

            for habit in habits:
                checkin = db.query(DailyCheckin).filter(
                    DailyCheckin.habit_id == habit.id,
                    DailyCheckin.date == for_date
                ).first()

                completed = checkin.completed if checkin else False

                if not completed:
                    db.add(PointTransaction(
                        user_id=user.id,
                        amount=habit.point_value,
                        type="failure",
                        reason=f"Missed {habit.name}",
                    ))
                    total_earned += habit.point_value
                    missed_habits.append(habit.name)

            points_row.current_points += total_earned
            points_row.lifetime_points += total_earned
            points_row.last_rollover_date = for_date

            if not habits:
                body = "_No good habits set up._"
            elif missed_habits:
                missed_list = "\n".join(f"❌ {name}" for name in missed_habits)
                body = f"{missed_list}\n+{total_earned} points"
            else:
                body = "✅ All good habits completed!"

            blocks.append(
                f"**{user.username}**\n{body}\n"
                f"Current: {points_row.current_points} · Lifetime: {points_row.lifetime_points}"
            )

        # One combined report for everyone scored in this run
        if blocks:
            existing = db.query(DailyReport).filter(DailyReport.date == for_date).first()
            if existing is None:
                message = f"📋 **Daily Report: {for_date.strftime('%A, %B %-d')}**\n\n" + "\n\n".join(blocks)
                if len(message) > 1900:  # Discord's limit is 2000 characters
                    message = message[:1900] + "…"
                db.add(DailyReport(date=for_date, message=message, status="pending"))

        db.commit()

    except Exception as e:
        print(f"ROLLOVER ERROR: {type(e).__name__}: {e}")
        db.rollback()
    finally:
        db.close()