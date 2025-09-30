import json, time, os
AUDIT_PATH = os.getenv('TRADE_AUDIT_PATH', '/mnt/data/trade_audit.jsonl')
def log(event_type: str, payload: dict):
    rec = {'ts': time.time(), 'event': event_type, **payload}
    with open(AUDIT_PATH, 'a') as f:
        f.write(json.dumps(rec)+'\n')
