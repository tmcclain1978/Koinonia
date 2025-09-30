# apps/auth_fastapi.py
from fastapi import APIRouter, Response, Request, HTTPException, Depends
from pydantic import BaseModel
from apps.security import USERS, verify_password, create_access_token, verify_token

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginIn(BaseModel):
    username: str
    password: str

COOKIE_NAME = "access_token"

@router.post("/login")
def login(data: LoginIn, res: Response):
    user = USERS.get(data.username)
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(sub=data.username, role=user["role"])

    # >>> This line goes here, in Python, not PowerShell <<<
    res.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/"   # important so Flask sees it too
    )

    return {"ok": True}

@router.post("/logout")
def logout(res: Response):
    res.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}

def get_current_user(req: Request):
    token = req.cookies.get(COOKIE_NAME)
    payload = verify_token(token) if token else None
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return payload
