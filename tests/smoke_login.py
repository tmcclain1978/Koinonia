import requests

BASE = "http://127.0.0.1:8000"

def test_login_and_dashboard():
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", data={"username":"admin","password":"password123","next":"/dashboard/"}, allow_redirects=False)
    assert r.status_code in (302,303)
    r2 = s.get(f"{BASE}/dashboard/")
    assert r2.status_code == 200
    assert "Dashboard" in r2.text or "McClain" in r2.text  # adjust to a string you expect
