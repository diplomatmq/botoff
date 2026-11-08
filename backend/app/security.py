import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return "$".join(
        [
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(base64.b64decode(hash_b64)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, base64.b64decode(hash_b64))


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _fernet() -> Fernet:
    settings = get_settings()
    material = settings.encryption_key or settings.secret_key
    if not material:
        raise RuntimeError("ENCRYPTION_KEY is not configured")
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("stored secret cannot be decrypted with the current key") from exc


def mask_token(token: str) -> str:
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}****{token[-4:]}"


def sanitize_payload(payload: dict | list | None) -> dict | list | None:
    if payload is None:
        return None
    if isinstance(payload, list):
        return [sanitize_payload(item) for item in payload]
    if isinstance(payload, dict):
        clean: dict = {}
        for key, value in payload.items():
            if key.lower() in {"authorization", "token", "api_key", "apikey", "password", "secret"}:
                clean[key] = "***"
            elif isinstance(value, (dict, list)):
                clean[key] = sanitize_payload(value)
            else:
                clean[key] = value
        return clean
    return payload
