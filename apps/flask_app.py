from pathlib import Path
from flask import Flask, request, jsonify, redirect, render_template
from jinja2 import ChoiceLoader, FileSystemLoader
from apps.security import verify_token

AUTH_COOKIE = "access_token"

BASE_DIR       = Path(__file__).resolve().parent.parent        # C:\AI Advisor
LEGACY_TPL     = BASE_DIR / "Legacy_flask" / "templates"       # Jinja templates
ROOT_TPL       = BASE_DIR / "templates"                        # (optional fallback)
LEGACY_STATIC  = BASE_DIR / "Legacy_flask" / "static"          # <-- your static root

flask_app = Flask(
    __name__,
    template_folder=str(LEGACY_TPL),
    static_folder=str(LEGACY_STATIC),      # serves /dashboard/static/* from Legacy_flask/static
    static_url_path="/static",
)

# Let Jinja search both template trees (Legacy first)
flask_app.jinja_loader = ChoiceLoader([
    FileSystemLoader(str(LEGACY_TPL)),
    FileSystemLoader(str(ROOT_TPL)),
])


class _CurrentUser:
    def __init__(self, payload):
        self._p = payload or {}
    @property
    def is_authenticated(self):
        return bool(self._p)
    def get_id(self):
        return self._p.get("sub")
    # optional: expose role/claims if your templates use them
    @property
    def role(self):
        return self._p.get("role")
    # Jinja may try to getattr anything; avoid AttributeErrors
    def __getattr__(self, name):
        return self._p.get(name)

@flask_app.context_processor
def inject_current_user():
    token = request.cookies.get(AUTH_COOKIE)
    payload = verify_token(token) if token else None
    return {"current_user": _CurrentUser(payload)}

@flask_app.get("/health")
def health():
    return jsonify(status="ok", app="flask")

@flask_app.before_request
def guard():
    allow = ("/health", "/favicon.ico")
    if request.path in allow or request.path.startswith("/static"):
        return
    tok = request.cookies.get(AUTH_COOKIE)
    if not tok or not verify_token(tok):
        return redirect("/auth/login?next=/dashboard/")

@flask_app.get("/", endpoint="dashboard_home")
def dashboard_home():
    return render_template("dashboard.html", title="Dashboard")
@flask_app.get("/__debug/templates")
def dbg_templates():
    return {
        "searchpath": getattr(flask_app.jinja_loader, "searchpath", str(flask_app.jinja_loader)),
        "template_folder": flask_app.template_folder,
        "static_folder": flask_app.static_folder,
    }

from flask import current_app
from jinja2 import TemplateNotFound

def template_exists(name: str) -> bool:
    try:
        current_app.jinja_loader.get_source(current_app.jinja_env, name)
        return True
    except TemplateNotFound:
        return False

def first_existing(cands: list[str]) -> str | None:
    for c in cands:
        if template_exists(c):
            return c
    return None

def add_page(slug: str, candidates: list[str]):
    endpoint = f"page_{slug.replace('/', '_')}"
    def _view(sl=slug, cand=candidates):
        name = first_existing(cand)
        if name:
            title = sl.split('/')[-1].replace('-', ' ').title()
            return render_template(name, title=title)
        current_app.logger.error("No template for '%s'. Tried: %s", sl, cand)
        return (f"Template not found for '{sl}'. Tried: {cand}", 404)
    flask_app.add_url_rule(f"/{slug}", endpoint=endpoint, view_func=_view, methods=["GET"])
    return endpoint

# Map slugs → candidate template names under Legacy_flask/templates (adjust if yours differ)
add_page("advisor",            ["advisor.html", "advisor/index.html", "pages/advisor.html"])
add_page("options/analytics",  ["options_analytics.html", "options/analytics.html", "options/analytics/index.html", "pages/options/analytics.html"])
add_page("paper/options",      ["paper_options.html", "paper/options.html", "paper/options/index.html", "pages/paper/options.html"])
add_page("audit",              ["audit.html", "audit/index.html", "pages/audit.html"])
add_page("admin/schwab",       ["admin/schwab.html", "admin/schwab/index.html", "pages/admin/schwab.html"])
add_page("trade/orders",       ["trade_orders.html", "trade/orders.html", "trade/orders/index.html", "pages/trade/orders.html"])
add_page("education",          ["education.html", "education/index.html", "pages/education.html"])
add_page("podcast",            ["podcast.html", "podcast/index.html", "pages/podcast.html"])
add_page("admin/education",    ["admin/education.html", "admin/education/index.html", "pages/admin/education.html"])
add_page("admin/podcast",      ["admin/podcast.html", "admin/podcast/index.html", "pages/admin/podcast.html"])
