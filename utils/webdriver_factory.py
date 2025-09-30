from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import os

def get_chrome_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    baked = os.getenv("CHROMEDRIVER_PATH")
    if baked and os.path.exists(baked):
        svc = Service(executable_path=baked)
    else:
        svc = Service()
    return get_chrome_driver(service=svc, options=opts)
