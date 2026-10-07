"""Google Drive OAuth: folder khusus aplikasi dan backup dengan Drive API."""
import os
from urllib.parse import urlencode
import requests
from .security import encrypt,decrypt
from .db import set_setting

AUTH='https://accounts.google.com/o/oauth2/v2/auth'
TOKEN='https://oauth2.googleapis.com/token'
BASE='https://www.googleapis.com/drive/v3/files'
UPLOAD='https://www.googleapis.com/upload/drive/v3/files'
SCOPE='https://www.googleapis.com/auth/drive.file'

def configured():
    return bool(os.getenv('GDRIVE_CLIENT_ID') and os.getenv('GDRIVE_CLIENT_SECRET'))

def authorize_url(state,redirect_uri):
    if not configured(): raise ValueError('Google OAuth belum dikonfigurasi.')
    return AUTH+'?'+urlencode({'client_id':os.getenv('GDRIVE_CLIENT_ID'),
        'redirect_uri':redirect_uri,'response_type':'code','scope':SCOPE,
        'access_type':'offline','prompt':'consent','include_granted_scopes':'true','state':state})

def exchange_code(code,redirect_uri):
    r=requests.post(TOKEN,data={'code':code,'client_id':os.getenv('GDRIVE_CLIENT_ID'),
       'client_secret':os.getenv('GDRIVE_CLIENT_SECRET'),'redirect_uri':redirect_uri,
       'grant_type':'authorization_code'},timeout=25)
    r.raise_for_status();payload=r.json()
    if not payload.get('refresh_token'):
        raise ValueError('Google tidak memberikan refresh token. Cabut akses aplikasi Google, kemudian hubungkan kembali.')
    return payload['refresh_token']

def access_token(encrypted_refresh):
    refresh=decrypt(encrypted_refresh)
    r=requests.post(TOKEN,data={'refresh_token':refresh,'client_id':os.getenv('GDRIVE_CLIENT_ID'),
       'client_secret':os.getenv('GDRIVE_CLIENT_SECRET'),'grant_type':'refresh_token'},timeout=25)
    r.raise_for_status()
    return r.json()['access_token']

def upload_backup(db,backup,name):
    from .db import settings
    opts=settings(db)
    if not opts['drive_refresh_token_enc']: raise ValueError('Hubungkan Google Drive pada halaman Pengaturan terlebih dahulu.')
    if not configured(): raise ValueError('GDRIVE_CLIENT_ID/GDRIVE_CLIENT_SECRET belum disetel.')
    headers={'Authorization':'Bearer '+access_token(opts['drive_refresh_token_enc'])}
    folder_id=opts.get('drive_folder_id','')
    if not folder_id:
        payload={'name':'SANJARA HADIR - Backup','mimeType':'application/vnd.google-apps.folder'}
        r=requests.post(BASE,json=payload,headers=headers,params={'fields':'id,name'},timeout=35)
        r.raise_for_status()
        folder_id=r.json()['id']
        set_setting(db,'drive_folder_id',folder_id)
        db.commit()  # Bebaskan kunci tulis SQLite sebelum upload jaringan yang mungkin lama.
    import json,secrets
    boundary='sanjara'+secrets.token_hex(16)
    meta={'name':name,'parents':[folder_id], 'description':'Backup SANJARA HADIR. Berisi data pribadi; batasi akses.'}
    body=(('--'+boundary+'\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n').encode()+
          json.dumps(meta).encode()+('\r\n--'+boundary+'\r\nContent-Type: application/zip\r\n\r\n').encode()+
          backup.getvalue()+('\r\n--'+boundary+'--\r\n').encode())
    r=requests.post(UPLOAD,params={'uploadType':'multipart','fields':'id,name,webViewLink'},
        data=body,headers={**headers,'Content-Type':'multipart/related; boundary='+boundary},timeout=120)
    r.raise_for_status()
    return r.json()
