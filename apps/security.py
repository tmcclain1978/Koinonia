# apps/security.py
import time, hashlib, hmac, jwt
from typing import Optional

SECRET_KEY = "CHANGE_ME_TO_A_LONG_RANDOM_STRING"  # move to .env for prod
ALGO = "HS256"
ACCESS_TTL = 60 * 60 * 8  # 8h

USERS = {  # replace with DB
    "admin": {"password_hash": hashlib.sha256(b"password123").hexdigest(), "role": "admin"},
}

def verify_password(plain: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(plain.encode()).hexdigest(), stored_hash)

def create_access_token(sub: str, role: str) -> str:
    now = int(time.time())
    payload = {"sub": sub, "role": role, "iat": now, "exp": now + ACCESS_TTL}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGO)

def verify_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGO])
    except Exception:
        return None
