"""Konfigurasi aman tahap awal. Jalankan: python -m scripts.setup"""
from getpass import getpass
from pathlib import Path
import os
import secrets

ROOT=Path(__file__).resolve().parent.parent
TARGET=ROOT/'.env'

def setup():
    if TARGET.exists():
        print('File .env sudah ada. Tidak diubah agar password dan token Drive tetap aman.')
        return
    print('=== INSTALASI AWAL SANJARA HADIR ===')
    username=input('Username admin [admin]: ').strip() or 'admin'
    if len(username)>45 or any(c.isspace() for c in username):
        raise ValueError('Username maksimal 45 karakter tanpa spasi.')
    while True:
        first=getpass('Kata sandi admin (minimal 10 karakter): ')
        second=getpass('Ulangi kata sandi: ')
        if len(first)<10:print('Minimal 10 karakter.');continue
        if first!=second:print('Kata sandi tidak sama.');continue
        if '\n' in first or '\r' in first:print('Karakter baris baru tidak diizinkan.');continue
        break
    # dotenv mendukung nilai yang diapit tanda kutip dan escape.
    def quoted(value):return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'
    target=('SECRET_KEY='+secrets.token_urlsafe(48)+'\n'
            +'ADMIN_USERNAME='+quoted(username)+'\n'
            +'ADMIN_PASSWORD='+quoted(first)+'\n'
            +'SESSION_SECURE=0\n'
            +'# Setelah deploy via HTTPS, ganti SESSION_SECURE=1\n'
            +'# GDRIVE_CLIENT_ID=\n# GDRIVE_CLIENT_SECRET=\n# GDRIVE_REDIRECT_URI=\n')
    with TARGET.open('x',encoding='utf-8') as f:f.write(target)
    if os.name!='nt':TARGET.chmod(0o600)
    print('File .env berhasil dibuat. Simpan rahasia; jangan unggah ke GitHub.')
    print('Jalankan: python start.py')

if __name__=='__main__':setup()
