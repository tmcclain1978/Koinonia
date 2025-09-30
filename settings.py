import os
from pydantic import BaseModel
class Settings(BaseModel):
    ENV: str = os.getenv("ENV","development")
    PAPER_MODE: bool = os.getenv("PAPER_MODE","true").lower()=="true"
    ENABLE_TRADING: bool = os.getenv("ENABLE_TRADING","false").lower()=="true"
    ALLOWED_ORIGINS: list[str] = os.getenv("ALLOWED_ORIGINS","*").split(",")
    DATABASE_URL: str | None = os.getenv("DATABASE_URL")
    REDIS_URL: str | None = os.getenv("REDIS_URL")
settings = Settings()
