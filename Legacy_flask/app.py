# legacy_flask/app.py
from flask import Flask, request, jsonify, g, render_template
from jose import jwt, JWTError
from .blueprints.admin import bp as admin_bp
from .blueprints.reports import bp as reports_bp
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(reports_bp, url_prefix="/reports")

import os

JWT_SECRET = os.getenv("APP_SECRET", "dev-secret")
JWT_ALGO = "HS256"
COOKIE_NAME = os.getenv("COOKIE_NAME", "access_token")
CSRF_COOKIE_NAME = os.getenv("CSRF_COOKIE_NAME", "csrf_token")

def create_app():
    app = Flask(
        __name__,
        template_folder="templates",   # e.g., legacy_flask/templates/...
        static_folder="static",        # e.g., legacy_flask/static/...
        static_url_path="/static"      # will resolve as /flask/static when mounted
    )

    PUBLIC = {"/health", "/"}  # add other public paths as needed

    @app.before_request
    def _jwt_guard():
        # 1) Always allow preflight
        if request.method == "OPTIONS":
            return ("", 204)

        # 2) Allow public endpoints and static assets
        if request.path in PUBLIC or request.path.startswith(app.static_url_path):
            return

        # 3) Get token from Authorization header OR HttpOnly cookie
        token = None
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]
        else:
            token = request.cookies.get(COOKIE_NAME)

        if not token:
            return jsonify({"detail": "Missing bearer token"}), 401

        # 4) CSRF check only for unsafe methods
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            hdr = request.headers.get("X-CSRF-Token")
            cky = request.cookies.get(CSRF_COOKIE_NAME)
            if not hdr or not cky or hdr != cky:
                return jsonify({"detail": "CSRF token missing/invalid"}), 403

        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
            g.user = payload
        except JWTError:
            return jsonify({"detail": "Invalid token"}), 401

    # Public health
    @app.get("/health")
    def health():
        return jsonify(ok=True)

    # Public landing (renders a template)
    @app.get("/")
    def home():
        # In your Jinja template, use {{ url_for('static', filename='app.css') }}
        # When mounted at /flask, url_for will auto-prefix paths with /flask
        return render_template("dashboard.html", app_name=os.getenv("APP_NAME", "Koinonia"))

    # Example protected route (JSON)
    @app.get("/report")
    def report():
        return jsonify(ok=True, user=g.get("user"))

    return app
