import json, logging, os, sys, time, uuid

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": int(time.time() * 1000),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            base["request_id"] = record.request_id
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)

def configure_json_logger(level: str | None = None):
    lvl = getattr(logging, (level or os.getenv("LOG_LEVEL","INFO")).upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(lvl)
    root.addHandler(handler)
    return root

def new_request_id() -> str:
    return uuid.uuid4().hex[:12]
