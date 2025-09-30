from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from starlette.middleware.wsgi import WSGIMiddleware

from apps.flask_app import flask_app
from apps.security import USERS, verify_password, create_access_token, verify_token

AUTH_COOKIE = "access_token"
app = FastAPI(title="Unified App")

# Health
@app.get("/api/health")
def api_health(): return {"status": "ok", "app": "fastapi"}

# Auth helpers
def current_user(req: Request):
    tok = req.cookies.get(AUTH_COOKIE)
    payload = verify_token(tok) if tok else None
    if not payload:
        raise HTTPException(401, "Not authenticated")
    return payload

# Protected example
@app.get("/api/secure")
def api_secure(user=Depends(current_user)):
    return {"ok": True, "user": user["sub"]}

# Login page (simple HTML)
LOGIN_HTML = """<!doctype html><title>Sign In</title>
<form method="post" action="/auth/login">
  <input type="hidden" name="next" value="{{next}}">
  <label>User <input name="username" value="admin"></label>
  <label>Pass <input name="password" type="password" value="password123"></label>
  <button>Sign In</button>
</form>"""

@app.get("/auth/login", response_class=HTMLResponse)
def login_page(next: str = "/dashboard/"):
    return HTMLResponse(LOGIN_HTML.replace("{{next}}", next))

@app.post("/auth/login")
def login(username: str = Form(...), password: str = Form(...), next: str = Form("/dashboard/")):
    user = USERS.get(username)
    if not user or not verify_password(password, user["password_hash"]):
        return RedirectResponse(url=f"/auth/login?next={next}", status_code=303)
    token = create_access_token(sub=username, role=user["role"])
    resp = RedirectResponse(url=next or "/dashboard/", status_code=303)
    resp.set_cookie(AUTH_COOKIE, token, httponly=True, samesite="lax", secure=False, path="/")
    return resp

@app.post("/auth/logout")
def logout():
    resp = RedirectResponse(url="/auth/login", status_code=303)
    resp.delete_cookie(AUTH_COOKIE, path="/")
    return resp

# Mount Flask UI
app.mount("/dashboard", WSGIMiddleware(flask_app))
