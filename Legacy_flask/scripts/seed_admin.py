# scripts/seed_admin.py
from api.db import SessionLocal, init_db
from api.models import User
from passlib.hash import bcrypt
import os

email = os.environ.get("ADMIN_EMAIL")
password = os.environ.get("ADMIN_PASSWORD")

if not email or not password:
    raise SystemExit("Set ADMIN_EMAIL and ADMIN_PASSWORD env vars when running this script.")

db = SessionLocal()
init_db()

u = db.query(User).filter(User.email == email.lower()).first()
if u:
    # promote existing user
    u.role = "admin"
    u.trade_enabled = True
    u.can_trade_paper = True
    u.can_trade_live = False
    db.commit()
    print(f"Promoted existing user to admin: {u.id} ({u.email})")
else:
    u = User(
        email=email.lower(),
        password_hash=bcrypt.hash(password),
        role="admin",
        trade_enabled=True,
        can_trade_paper=True,
        can_trade_live=False,
    )
    db.add(u)
    db.commit()
    print(f"Created admin user id: {u.id} ({u.email})")
