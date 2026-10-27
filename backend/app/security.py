import base64
import hashlib
import hmac
import os
import time

from cryptography.fernet import Fernet

from .db import DATA_DIR

SESSION_TTL = 7 * 24 * 3600

_secret_file = DATA_DIR / "secret.key"
if not _secret_file.exists():
    _secret_file.write_bytes(os.urandom(32))
    os.chmod(_secret_file, 0o600)
_SECRET = _secret_file.read_bytes()
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"enc" + _SECRET).digest()))


def encrypt(text: str) -> str:
    return _fernet.encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


def check_password(pw: str) -> bool:
    expected = os.environ.get("APP_PASSWORD", "")
    return bool(expected) and hmac.compare_digest(pw.encode(), expected.encode())


def _sign(payload: str) -> str:
    return hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = str(int(time.time()) + SESSION_TTL)
    return f"{exp}.{_sign(exp)}"


def verify_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(exp)):
        return False
    return exp.isdigit() and int(exp) > time.time()
