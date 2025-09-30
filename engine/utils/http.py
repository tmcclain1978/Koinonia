import httpx, time, random
from typing import Any, Dict

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=10.0)

def new_client() -> httpx.Client:
    return httpx.Client(timeout=DEFAULT_TIMEOUT)

def with_backoff(fn, retries: int = 4, base: float = 0.25):
    for i in range(retries):
        try:
            return fn()
        except httpx.HTTPError:
            if i == retries - 1: raise
            time.sleep(base * (2**i) + random.random() * 0.1)
