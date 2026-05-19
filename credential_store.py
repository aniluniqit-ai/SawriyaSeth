import base64
import binascii
import hashlib
import logging
import os
from typing import Dict

logger = logging.getLogger("CredentialStore")

SENSITIVE_KEYS = {"access_token", "mpin", "totp_secret", "api_hash", "bot_token"}


def _device_key() -> bytes:
    seed = f"{os.environ.get('COMPUTERNAME','pc')}|{os.environ.get('USERNAME','user')}"
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def encrypt_text(value: str) -> str:
    if not value:
        return value
    raw = value.encode("utf-8")
    token = _xor_bytes(raw, _device_key())
    return "enc:" + base64.urlsafe_b64encode(token).decode("ascii")


def decrypt_text(value: str) -> str:
    """
    Decrypt values saved with encrypt_text. Never raises: wrong PC / corrupt blob
    returns empty string so app can start; user re-saves secrets from Settings.
    """
    if not value or not isinstance(value, str) or not value.startswith("enc:"):
        return value
    try:
        payload = value[4:]
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        plain = _xor_bytes(raw, _device_key())
        return plain.decode("utf-8")
    except (UnicodeDecodeError, ValueError, binascii.Error, OSError) as e:
        logger.warning(
            "Credential decrypt failed (wrong machine or old/corrupt enc:). "
            "Re-enter Kotak/Telegram secrets in Settings and Save. Detail: %s",
            e,
        )
        return ""


def encrypt_sensitive_dict(data: Dict) -> Dict:
    out = dict(data or {})
    for k in list(out.keys()):
        if k in SENSITIVE_KEYS and isinstance(out[k], str):
            v = out[k]
            if not v:
                continue
            if v.startswith("enc:"):
                if decrypt_text(v):
                    out[k] = v
                else:
                    out[k] = v
            else:
                out[k] = encrypt_text(v)
    return out


def decrypt_sensitive_dict(data: Dict) -> Dict:
    out = dict(data or {})
    for k in list(out.keys()):
        if k in SENSITIVE_KEYS and isinstance(out[k], str):
            out[k] = decrypt_text(out[k])
    return out
