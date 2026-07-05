# app/crypto.py
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _fernet():
    """Derive a stable Fernet key from the app's own SECRET_KEY - no extra secret
    to configure or lose track of, just reuses what's already there."""
    digest = hashlib.sha256(current_app.config['SECRET_KEY'].encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value):
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value):
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None
