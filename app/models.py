from sqlalchemy import Column, Integer, Text, Boolean
from app.database import Base

class Habit(Base):
    __tablename__ = "habits"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    type = Column(Text, nullable=False)
    point_value = Column(Integer, nullable=False, default=1)
    active = Column(Boolean, nullable=False, default=True)
