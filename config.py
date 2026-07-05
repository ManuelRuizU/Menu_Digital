import os
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')


def _load_or_create_secret_key():
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key

    os.makedirs(INSTANCE_DIR, exist_ok=True)
    key_path = os.path.join(INSTANCE_DIR, 'secret_key')
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            return f.read().strip()

    key = secrets.token_hex(32)
    with open(key_path, 'w') as f:
        f.write(key)
    return key


class Config:
    SECRET_KEY = _load_or_create_secret_key()
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOADED_PHOTOS_DEST = os.path.join(BASE_DIR, 'app/static/uploads')
    LOGO_UPLOAD_DIR = os.path.join(BASE_DIR, 'app/static/uploads/logos')
    LOGO_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    PRODUCT_UPLOAD_DIR = os.path.join(BASE_DIR, 'app/static/uploads/products')
    PRODUCT_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024  # 12 MB - raw phone photos come in large; the server compresses them on save

    # Secure by default (cookie only sent over HTTPS) - both documented deployment paths
    # (VPS+certbot, PythonAnywhere) always serve over HTTPS. Set DISABLE_SECURE_COOKIES=1
    # only for local testing over plain http://127.0.0.1.
    SESSION_COOKIE_SECURE = os.environ.get('DISABLE_SECURE_COOKIES') != '1'

