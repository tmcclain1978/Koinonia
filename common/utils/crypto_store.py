from cryptography.fernet import Fernet
import os

_key = os.getenv("ENCRYPTION_KEY")
if not _key:
    raise RuntimeError("ENCRYPTION_KEY missing")
_f = Fernet(_key.encode() if isinstance(_key, str) else _key)

def enc(s: str) -> bytes:
    return _f.encrypt(s.encode())

def dec(b: bytes) -> str:
    return _f.decrypt(b).decode()
