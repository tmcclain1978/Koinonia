import os, time, requests

API_BASE = os.getenv("SCHWAB_API_BASE").rstrip("/")

class SchwabAPI:
    def __init__(self, access_token_supplier, refresh_fn):
        """
        access_token_supplier: callable -> str (returns a valid access token)
        refresh_fn: callable -> None (refreshes and persists tokens when 401)
        """
        self._get_token = access_token_supplier
        self._refresh = refresh_fn

    def _headers(self):
        return {"Authorization": f"Bearer {self._get_token()}",
                "Accept": "application/json"}

    def _request(self, method, path, **kwargs):
        url = f"{API_BASE}{path}"
        r = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        if r.status_code == 401:
            # try refresh once
            self._refresh()
            r = requests.request(method, url, headers=self._headers(), timeout=30, **kwargs)
        r.raise_for_status()
        return r

    # --- Accounts / Positions ---
    def accounts(self):
        r = self._request("GET", "/trader/v1/accounts")
        return r.json()

    def positions(self, account_id: str):
        r = self._request("GET", f"/trader/v1/accounts/{account_id}/positions")
        return r.json()

    # --- Market Data (quotes) ---
    def quotes(self, symbols: list[str]):
        params = {"symbols": ",".join(symbols)}
        r = self._request("GET", "/marketdata/v1/quotes", params=params)
        return r.json()

    # --- Orders ---
    def place_order(self, account_id: str, order: dict):
        r = self._request("POST", f"/trader/v1/accounts/{account_id}/orders",
                          json=order,
                          headers={**self._headers(), "Content-Type": "application/json"})
        # Schwab may return 201 with Location header for order id
        return {"status": r.status_code, "location": r.headers.get("Location")}
