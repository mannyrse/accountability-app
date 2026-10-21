import pytz
from datetime import datetime

EASTERN = pytz.timezone("America/Chicago")

def eastern_today():
    return datetime.now(EASTERN).date()