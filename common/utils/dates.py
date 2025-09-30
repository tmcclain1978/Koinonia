from datetime import datetime, timezone

def tz_now():
  return datetime.now(timezone.utc)
