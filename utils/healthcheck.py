def run_full_healthcheck(db_session=None, scraper_fn=None, forecast_fn=None) -> dict:
    results = {"db": False, "scraper": False, "forecast": False, "status": "fail"}
    try:
        if db_session:
            db_session.execute("SELECT 1")
            results["db"] = True
    except Exception as e:
        results["db_error"] = str(e)

    try:
        if scraper_fn:
            ok = scraper_fn()
            results["scraper"] = bool(ok)
    except Exception as e:
        results["scraper_error"] = str(e)

    try:
        if forecast_fn:
            ok = forecast_fn()
            results["forecast"] = bool(ok)
    except Exception as e:
        results["forecast_error"] = str(e)

    if all([results.get("db"), results.get("scraper"), results.get("forecast")]):
        results["status"] = "ok"
    return results
