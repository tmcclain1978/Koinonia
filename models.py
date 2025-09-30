# models.py (or wherever your models live)
from __future__ import annotations
import os
from datetime import datetime
from cryptography.fernet import Fernet, InvalidToken
from extensions import db
from flask_login import UserMixin

class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
def _fernet():
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is not set")
    return Fernet(key.encode() if isinstance(key, str) else key)

class SchwabCredential(db.Model):
    __tablename__ = "schwab_credentials"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    enc_access_token  = db.Column(db.LargeBinary, nullable=False)
    enc_refresh_token = db.Column(db.LargeBinary, nullable=False)
    expires_at = db.Column(db.Integer, nullable=False)  # epoch seconds
    scope = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now(), nullable=False)

    # --- helpers ---
    @classmethod
    def upsert(cls, user_id: int, *, access_token: str, refresh_token: str, expires_at: int, scope: str | None):
        f = _fernet()
        rec = cls.query.filter_by(user_id=user_id).one_or_none()
        if not rec:
            rec = cls(user_id=user_id)
            db.session.add(rec)
        rec.enc_access_token  = f.encrypt(access_token.encode())
        rec.enc_refresh_token = f.encrypt(refresh_token.encode())
        rec.expires_at = int(expires_at)
        rec.scope = scope
        db.session.commit()
        return rec

    def tokens(self) -> dict:
        f = _fernet()
        try:
            return {
                "access_token":  f.decrypt(self.enc_access_token).decode(),
                "refresh_token": f.decrypt(self.enc_refresh_token).decode(),
                "expires_at":    int(self.expires_at),
                "scope":         self.scope,
            }
        except InvalidToken:
            raise RuntimeError("Failed to decrypt Schwab tokens; check ENCRYPTION_KEY")
