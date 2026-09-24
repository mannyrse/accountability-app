from sqlalchemy import Column, Integer, Text, Boolean, Date, DateTime, ForeignKey
from app.database import Base
from datetime import datetime, timezone

class Habit(Base):
    __tablename__ = "habits"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    type = Column(Text, nullable=False)
    point_value = Column(Integer, nullable=False, default=1)
    active = Column(Boolean, nullable=False, default=True)


class DailyCheckin(Base):
    __tablename__ = "daily_checkins"

    id = Column(Integer, primary_key=True)
    habit_id = Column(Integer, ForeignKey("habits.id"), nullable=False)
    date = Column(Date, nullable=False)
    completed = Column(Boolean, nullable=False, default=False)
    point_awarded = Column(Boolean, nullable=False, default=False)
    point_transaction_id = Column(Integer, ForeignKey("point_transactions.id"), nullable=True)


class Points(Base):
    __tablename__ = "points"

    id = Column(Integer, primary_key=True)
    current_points = Column(Integer, nullable=False, default=0)
    lifetime_points = Column(Integer, nullable=False, default=0)
    last_rollover_date = Column(Date, nullable=True)


class PointTransaction(Base):
    __tablename__ = "point_transactions"

    id = Column(Integer, primary_key=True)
    amount = Column(Integer, nullable=False)
    type = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Reward(Base):
    __tablename__ = "rewards"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    point_cost = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False, default=True)

class PendingNotification(Base):
    __tablename__ = "pending_notifications"

    id = Column(Integer, primary_key=True)
    habit_id = Column(Integer, ForeignKey("habits.id"), nullable=False)
    date = Column(Date, nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    status = Column(Text, nullable=False)

class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, unique=True)
    message = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))