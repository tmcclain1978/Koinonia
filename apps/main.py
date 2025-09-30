# apps/main.py
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.wsgi import WSGIMiddleware

from apps.flask_app import flask_app
from apps.security import USERS, verify_password, create_access_token, verify_token

AUTH_COOKIE = "access_token"

app = FastAPI(title="Unified App")

@app.get("/", include_in_schema=False)
def root_redirect(req: Request):
    token = req.cookies.get(AUTH_COOKIE)
    if token and verify_token(token):
        return RedirectResponse("/dashboard/", status_code=303)
    return RedirectResponse("/auth/login?next=/dashboard/", status_code=303)

# ---------- FastAPI: health ----------
@app.get("/api/health")
def api_health():
    return {"status": "ok", "app": "fastapi"}

# ---------- FastAPI: auth helpers ----------
def get_current_user(req: Request):
    token = req.cookies.get(AUTH_COOKIE)
    payload = verify_token(token) if token else None
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return payload

# ---------- FastAPI: protected example ----------
@app.get("/api/secure")
def api_secure(user=Depends(get_current_user)):
    return {"ok": True, "user": user["sub"]}

# ---------- FastAPI: Login page (HTML) ----------
LOGIN_HTML = """
<!doctype html>
<title>Sign In</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  body { font-family: system-ui, Arial, sans-serif; max-width: 420px; margin: 10vh auto; }
  form { display: grid; gap: 10px; }
  input, button { padding: 10px; font-size: 16px; }
  .card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; }
</style>
<div class="card">
  <h2>Sign In</h2>
  <form method="post" action="/auth/login">
    <input type="hidden" name="next" value="{{next}}">
    <label>Username
      <input name="username" value="admin" autocomplete="username" />
    </label>
    <label>Password
      <input name="password" type="password" value="password123" autocomplete="current-password" />
    </label>
    <button type="submit">Sign In</button>
  </form>
</div>
"""

@app.get("/auth/login", response_class=HTMLResponse)
def login_page(next: str = "/dashboard/"):
    # very small templating (no Jinja needed)
    return HTMLResponse(LOGIN_HTML.replace("{{next}}", next))

# ---------- FastAPI: Login POST (sets HttpOnly cookie, redirects) ----------
@app.post("/auth/login")
def login(username: str = Form(...), password: str = Form(...), next: str = Form("/dashboard/")):
    user = USERS.get(username)
    if not user or not verify_password(password, user["password_hash"]):
        # back to login with error (keep it simple for now)
        return RedirectResponse(url="/auth/login?next=" + next, status_code=303)
    token = create_access_token(sub=username, role=user["role"])
    resp = RedirectResponse(url=next or "/dashboard/", status_code=303)
    # cookie readable by both stacks
    resp.set_cookie(
        key=AUTH_COOKIE, value=token,
        httponly=True, samesite="lax", secure=False, path="/"
    )
    return resp

@app.post("/auth/logout")
def logout():
    resp = RedirectResponse(url="/auth/login", status_code=303)
    resp.delete_cookie(AUTH_COOKIE, path="/")
    return resp

# ---------- Mount Flask under /dashboard ----------
app.mount("/dashboard", WSGIMiddleware(flask_app))
