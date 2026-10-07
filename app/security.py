"""Password hashing, CSRF, dan token OAuth terenkripsi."""
import base64
import hashlib
import hmac
import os
import secrets
from cryptography.fernet import Fernet
from fastapi import HTTPException


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 310000)
    return 'pbkdf2_sha256$310000$' + salt.hex() + '$' + digest.hex()

def check_password(password, stored):
    try:
        label, rounds, salt, digest = stored.split('$')
        if label != 'pbkdf2_sha256': return False
        actual = hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),int(rounds))
        return hmac.compare_digest(actual,bytes.fromhex(digest))
    except (ValueError,TypeError): return False

def csrf(request):
    if 'csrf' not in request.session:
        request.session['csrf'] = secrets.token_urlsafe(32)
    return request.session['csrf']

def validate_csrf(request, form=None):
    expected = request.session.get('csrf','')
    provided = request.headers.get('X-CSRF-Token','') if form is None else str(form.get('_csrf',''))
    if not expected or not hmac.compare_digest(provided,expected):
        raise HTTPException(403,'Token keamanan formulir tidak valid. Segarkan halaman.')

def fernet():
    key = os.environ.get('SECRET_KEY','')
    if len(key) < 32:
        raise RuntimeError('SECRET_KEY wajib minimal 32 karakter untuk menghubungkan Google Drive.')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))

def encrypt(text): return fernet().encrypt(text.encode()).decode()
def decrypt(text): return fernet().decrypt(text.encode()).decode()
