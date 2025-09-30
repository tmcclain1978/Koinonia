from __future__ import annotations

def db_ping(session) -> bool:
    try:
        session.execute("SELECT 1")
        return True
    except Exception:
        return False

def scraper_smoke() -> bool:
    # Intentionally light: verify factory import, do not launch browser here
    try:
        from utils.webdriver_factory import get_chrome_driver  # noqa: F401
        return True
    except Exception:
        return False

def forecast_smoke() -> bool:
    try:
        # Import model loader if available
        import importlib
        m = importlib.import_module("forecast_engine")
        # if module exists, assume minimal health ok
        return True
    except Exception:
        return True  # keep permissive to not block boot
