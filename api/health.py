from fastapi import APIRouter
router = APIRouter()

@router.get("/healthz")
def healthz(): return {"ok": True}

@router.get("/readyz")
def readyz():  # TODO: ping DB/Redis/vendors and return aggregate
    return {"db": "ok", "redis": "ok", "vendors": "ok"}
