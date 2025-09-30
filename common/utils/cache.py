import os, time
from typing import Optional
try:
    import redis
except Exception:
    redis=None
class Cache:
    def __init__(self):
        self.ttl_store={}
        self.r=None
        url=os.getenv("REDIS_URL")
        if redis and url:
            try:
                self.r=redis.from_url(url, decode_responses=True)
            except Exception:
                self.r=None
    def get(self,key:str)->Optional[str]:
        if self.r:
            try: return self.r.get(key)
            except Exception: return None
        now=time.time()
        if key in self.ttl_store:
            val,exp=self.ttl_store[key]
            if exp is None or exp>now: return val
            del self.ttl_store[key]
        return None
    def set(self,key:str,val:str,ttl_seconds:int=60):
        if self.r:
            try:
                self.r.setex(key, ttl_seconds, val); return
            except Exception: pass
        exp=time.time()+ttl_seconds if ttl_seconds else None
        self.ttl_store[key]=(val,exp)
