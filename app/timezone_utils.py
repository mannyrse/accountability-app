import pytz
from datetime import datetime

EASTERN = pytz.timezone("America/New_York")

def eastern_today():
    return datetime.now(EASTERN).date()