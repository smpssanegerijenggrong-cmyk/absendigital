"""SANJARA HADIR — FastAPI, HTML server-side, absensi QR dan GPS."""
import io
import math
import os
import secrets
import sqlite3
import csv
import zipfile
from datetime import date,time,timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / '.env', override=False)

from fastapi import FastAPI,Request,Form,UploadFile,File,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse,StreamingResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel,Field
from openpyxl import load_workbook,Workbook
import qrcode

from .db import init_db,connect,settings,set_setting,log,DB_PATH,LETTERS_DIR,IS_VERCEL
from .security import password_hash,check_password,csrf,validate_csrf,encrypt
from .services import now_wib,late_status,distance_m,school_day,visible_status,students_query,attendance_report,parse_day,parse_month
from .reports import make_report
from .backup import make_backup
from . import drive

BASE=Path(__file__).resolve().parent
SECRET=os.environ.get('SECRET_KEY','') or secrets.token_urlsafe(48)
if SECRET.startswith('GANTI_'):
    raise RuntimeError('SECRET_KEY masih contoh; ganti dengan nilai random yang aman.')
app=FastAPI(title='SANJARA HADIR — School Edition',version='2.0.0',docs_url=None,redoc_url=None)
app.add_middleware(SessionMiddleware,secret_key=SECRET,session_cookie='sanjara_session',
                   same_site='lax',https_only=os.getenv('SESSION_SECURE','0')=='1',max_age=60*60*10)
app.mount('/static',StaticFiles(directory=str(BASE/'static')),name='static')
templates=Jinja2Templates(directory=str(BASE/'templates'))
init_db()

# Admin pertama dibuat dari variabel lingkungan, tanpa password bawaan.
def bootstrap_admin():
    username=os.environ.get('ADMIN_USERNAME','admin').strip()
    password=os.environ.get('ADMIN_PASSWORD','')
    if not password: return
    if password.startswith('GANTI_'): raise RuntimeError('ADMIN_PASSWORD masih contoh; ganti dengan password unik.')
    if not os.environ.get('SECRET_KEY'): raise RuntimeError('SECRET_KEY harus disetel agar sesi login aman.')
    if len(password)<10: raise RuntimeError('ADMIN_PASSWORD minimal 10 karakter')
    with connect() as db:
        if db.execute('SELECT 1 FROM users').fetchone() is None:
            db.execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES (?,?,?,?,?)',
                       (username,'Administrator Sekolah',password_hash(password),'ADMIN',now_wib().isoformat()))
bootstrap_admin()

class QRPayload(BaseModel):
    token:str=Field(min_length=10,max_length=250)
    latitude:float
    longitude:float
    accuracy:float

class RequireLogin(Exception): pass

@app.exception_handler(RequireLogin)
async def require_login_handler(request,exc):
    return RedirectResponse('/login',status_code=303)

@app.middleware('http')
async def headers_middleware(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    if request.url.path not in ('/health',) and not request.url.path.startswith('/static'):
        response.headers['Cache-Control']='no-store'
    return response

def get_user(request,admin=False,api=False):
    uid=request.session.get('uid')
    if not uid:
        if api: raise HTTPException(401,'Silakan login sebagai petugas.')
        raise RequireLogin()
    with connect() as db:
        user=db.execute('SELECT id,username,display_name,role,active FROM users WHERE id=?',(uid,)).fetchone()
    if not user or not user['active']:
        request.session.clear()
        if api: raise HTTPException(401,'Sesi tidak berlaku.')
        raise RequireLogin()
    if admin and user['role']!='ADMIN': raise HTTPException(403,'Hanya administrator yang berwenang.')
    return dict(user)

def notice(request,message,kind='success'):
    request.session['notices']=(request.session.get('notices',[])+[{'message':str(message),'kind':kind}])[-5:]

def goto(path): return RedirectResponse(path,status_code=303)

def render(request,page,**context):
    user=context.pop('user',None)
    base={'request':request,'user':user,'csrf':csrf(request),
          'notices':request.session.pop('notices',[]),
          'today':now_wib().date().isoformat(),'current_year':now_wib().year,
          'page':page}
    base.update(context)
    return templates.TemplateResponse(request,page+'.html',base)

def client_ip(request):
    return request.client.host if request.client else ''

def submitted_form(request,form):
    validate_csrf(request,form)
    return form

def val_name(name,maximum=120):
    name=str(name).strip()
    if not name or len(name)>maximum: raise ValueError('Nama/teks harus diisi dan tidak terlalu panjang.')
    return name

def class_id(db,name,auto_create=True):
    name=val_name(name,45)
    row=db.execute('SELECT id FROM classes WHERE name=? COLLATE NOCASE',(name,)).fetchone()
    if row: return row['id']
    if not auto_create: raise ValueError('Kelas tidak ditemukan.')
    db.execute('INSERT INTO classes(name) VALUES (?)',(name,))
    return db.execute('SELECT last_insert_rowid()').fetchone()[0]

def read_xlsx(file_bytes,max_rows=5000):
    if len(file_bytes)>8*1024*1024: raise ValueError('Berkas maksimal 8 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            if len(z.infolist())>1200 or sum(info.file_size for info in z.infolist())>75*1024*1024:
                raise ValueError('Struktur Excel terlalu besar; kemungkinan file tidak aman.')
        wb=load_workbook(io.BytesIO(file_bytes),read_only=True,data_only=True)
        ws=wb.active
        rows=ws.iter_rows(values_only=True)
        header=[str(v or '').strip().upper() for v in next(rows)]
        if len(header)>60: raise ValueError('Terlalu banyak kolom Excel (maksimum 60).')
        data=[]
        for i,row in enumerate(rows,2):
            if len(data)>=max_rows: raise ValueError(f'Maksimal {max_rows} baris.')
            if not any(v is not None and str(v).strip() for v in row): continue
            data.append((i,{name:cell_string(row[idx]) for idx,name in enumerate(header) if name}))
        wb.close()
        return header,data
    except StopIteration: raise ValueError('Berkas Excel kosong.')
    except (OSError,ValueError,KeyError,TypeError) as exc: raise ValueError(f'Excel tidak valid: {exc}')

def cell_string(value):
    if value is None: return ''
    if isinstance(value,float) and value.is_integer(): return str(int(value))
    return str(value).strip()

@app.get('/health')
def health(): return {'status':'ok','name':'SANJARA HADIR','database':'sqlite-persistent-volume-required','version':'2.0.1','vercel':IS_VERCEL,'persistent_storage':not IS_VERCEL or bool(os.environ.get('DATA_DIR'))}

@app.get('/login',response_class=HTMLResponse)
def login_page(request:Request):
    if request.session.get('uid'): return goto('/')
    with connect() as db: installed=bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())
    return render(request,'login',installed=installed,user=None)

@app.post('/login')
async def login_action(request:Request):
    form=submitted_form(request,await request.form())
    username=str(form.get('username','')).strip()
    password=str(form.get('password',''))
    ip=client_ip(request)
    since=(now_wib()-timedelta(minutes=15)).isoformat()
    with connect() as db:
        db.execute('DELETE FROM login_failures WHERE created_at<?',(since,))
        fail_count=db.execute('SELECT COUNT(*) FROM login_failures WHERE ip=? AND username=? COLLATE NOCASE',
                              (ip,username)).fetchone()[0]
        if fail_count>=10:
            notice(request,'Terlalu banyak percobaan login. Coba lagi setelah 15 menit.','error')
            return goto('/login')
        user=db.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE AND active=1',(username,)).fetchone()
        if user and check_password(password,user['password_hash']):
            db.execute('DELETE FROM login_failures WHERE ip=? AND username=? COLLATE NOCASE',(ip,username))
            request.session.clear();request.session['uid']=user['id'];csrf(request)
            log(db,user['id'],'LOGIN','Login petugas',ip)
            return goto('/')
        db.execute('INSERT INTO login_failures(ip,username,created_at) VALUES (?,?,?)',
                   (ip,username,now_wib().isoformat()))
    notice(request,'Username atau kata sandi tidak tepat.','error')
    return goto('/login')

@app.post('/logout')
async def logout_action(request:Request):
    get_user(request)
    submitted_form(request,await request.form())
    request.session.clear()
    return goto('/login')

@app.get('/',response_class=HTMLResponse)
def dashboard(request:Request,day:str|None=None,kelas:str='',q:str=''):
    user=get_user(request)
    try: day=parse_day(day or now_wib().date().isoformat())
    except ValueError: raise HTTPException(400,'Tanggal tidak valid.')
    if len(kelas)>45 or len(q)>100: raise HTTPException(400,'Filter terlalu panjang')
    with connect() as db:
        opts=settings(db);classes=db.execute('SELECT * FROM classes WHERE active=1 ORDER BY name').fetchall()
        all_students=students_query(db,kelas,q)
        items=[];counts={k:0 for k in ['HADIR','TERLAMBAT','SAKIT','IJIN','ALPA','BELUM ABSEN','LIBUR']}
        for s in all_students:
            if day < s['joined_on']: continue
            status=visible_status(db,s['id'],day,opts,s['joined_on'])
            counts[status]=counts.get(status,0)+1
            mark=db.execute('SELECT scanned_at FROM attendance WHERE student_id=? AND day=?',(s['id'],day)).fetchone()
            items.append({'student':s,'status':status,'time':mark['scanned_at'][11:19] if mark and mark['scanned_at'] else '—'})
        latest=db.execute('''SELECT a.*,s.name,c.name AS class_name FROM attendance a JOIN students s ON s.id=a.student_id
           JOIN classes c ON c.id=s.class_id WHERE a.day=? ORDER BY a.id DESC LIMIT 8''',(day,)).fetchall()
    return render(request,'dashboard',user=user,settings=opts,classes=classes,items=items,
                  counts=counts,total=len(items),day=day,kelas=kelas,q=q,latest=latest)

@app.get('/classes')
def classes_page(request:Request):
    user=get_user(request)
    with connect() as db:
        classes=db.execute('''SELECT c.*,COUNT(s.id) AS total FROM classes c LEFT JOIN students s ON c.id=s.class_id AND s.active=1
           GROUP BY c.id ORDER BY c.name''').fetchall()
    return render(request,'classes',user=user,classes=classes)

@app.post('/classes/add')
async def add_class(request:Request):
    user=get_user(request,admin=True); form=submitted_form(request,await request.form())
    try:
        with connect() as db:
            klass=val_name(form.get('name',''),45);class_id(db,klass)
            log(db,user['id'],'CLASS_ADD',klass,client_ip(request))
        notice(request,'Kelas berhasil disimpan.')
    except (ValueError,sqlite3.Error) as exc: notice(request,str(exc),'error')
    return goto('/classes')

@app.post('/classes/import')
async def import_classes(request:Request):
    user=get_user(request,admin=True);form=submitted_form(request,await request.form())
    upload=form.get('file')
    try:
        if not upload or not hasattr(upload,'read') or not upload.filename.lower().endswith(('.csv','.xlsx')):
            raise ValueError('Gunakan berkas .xlsx atau .csv berkolom KELAS.')
        raw=await upload.read(8*1024*1024+1)
        if upload.filename.lower().endswith('.xlsx'):
            header,data=read_xlsx(raw,max_rows=500)
        else:
            text=raw.decode('utf-8-sig')
            entries=list(csv.DictReader(io.StringIO(text)))
            if len(entries)>500: raise ValueError('Maksimal 500 kelas.')
            header=[str(k).strip().upper() for k in (entries[0].keys() if entries else [])]
            data=[(i+2,{str(k).strip().upper():str(v or '').strip() for k,v in item.items()}) for i,item in enumerate(entries)]
        if not {'KELAS'} & set(header) and 'NAMA KELAS' not in header: raise ValueError('Header wajib KELAS atau NAMA KELAS.')
        with connect() as db:
            before=db.execute('SELECT COUNT(*) FROM classes').fetchone()[0]
            for _,item in data:
                name=item.get('KELAS','') or item.get('NAMA KELAS','')
                if name: class_id(db,name)
            after=db.execute('SELECT COUNT(*) FROM classes').fetchone()[0]
            log(db,user['id'],'CLASS_IMPORT',f'{after-before} kelas baru',client_ip(request))
        notice(request,f'Impor selesai: {after-before} kelas baru.')
    except Exception as exc: notice(request,f'Impor kelas gagal: {exc}','error')
    return goto('/classes')

@app.get('/classes/template')
def class_template(request:Request):
    get_user(request)
    wb=Workbook();ws=wb.active;ws.title='IMPORT KELAS'
    ws.append(['KELAS']);ws.append(['VII A']);ws.append(['VII B'])
    buffer=io.BytesIO();wb.save(buffer);buffer.seek(0)
    return StreamingResponse(buffer,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':'attachment; filename="template_kelas_sanjara.xlsx"'})

@app.get('/students')
def students_page(request:Request,kelas:str='',q:str=''):
    user=get_user(request)
    with connect() as db:
        rows=students_query(db,kelas,q,active_only=False)
        classes=db.execute('SELECT * FROM classes ORDER BY name').fetchall()
    return render(request,'students',user=user,students=rows,classes=classes,kelas=kelas,q=q)

@app.post('/students/add')
async def add_student(request:Request):
    user=get_user(request,admin=True);form=submitted_form(request,await request.form())
    try:
        name=val_name(form.get('name',''))
        gender=str(form.get('gender','')).upper()
        if gender not in ('L','P'): raise ValueError('Jenis kelamin harus L atau P.')
        nipd=str(form.get('nipd','')).strip()[:35];nisn=str(form.get('nisn','')).strip()[:35]
        with connect() as db:
            duplicate=db.execute('SELECT 1 FROM students WHERE (? != "" AND nisn=?) OR (? != "" AND nipd=?)',
                                 (nisn,nisn,nipd,nipd)).fetchone()
            if duplicate: raise ValueError('NIPD/NISN tersebut sudah terdaftar.')
            klass=class_id(db,form.get('class_name',''))
            db.execute('''INSERT INTO students(nipd,nisn,name,gender,class_id,qr_token,joined_on)
                 VALUES (?,?,?,?,?,?,?)''',(nipd,nisn,name,gender,klass,secrets.token_urlsafe(32),now_wib().date().isoformat()))
            log(db,user['id'],'STUDENT_ADD',name,client_ip(request))
        notice(request,'Siswa berhasil ditambahkan. QR langsung tersedia.')
    except (ValueError,sqlite3.Error) as exc: notice(request,str(exc),'error')
    return goto('/students')

@app.post('/students/import')
async def import_students(request:Request):
    user=get_user(request,admin=True);form=submitted_form(request,await request.form());upload=form.get('file')
    try:
        if not upload or not hasattr(upload,'read') or not upload.filename.lower().endswith('.xlsx'):
            raise ValueError('Unggah Excel .xlsx dengan header NIPD, NISN, NAMA, JENIS KELAMIN, KELAS.')
        header,data=read_xlsx(await upload.read(8*1024*1024+1))
        fields={'NIPD','NISN','NAMA','JENIS KELAMIN','KELAS'}
        if not fields.issubset(set(header)):raise ValueError('Kolom Excel tidak sesuai. Gunakan template impor siswa.')
        inserted=skipped=0
        with connect() as db:
            for index,item in data:
                name=val_name(item['NAMA'])
                sex=item['JENIS KELAMIN'].upper()
                sex={'LAKI-LAKI':'L','LAKI LAKI':'L','PEREMPUAN':'P'}.get(sex,sex)
                if sex not in ('L','P'):raise ValueError(f'Baris {index}: jenis kelamin salah.')
                nipd=item['NIPD'][:35];nisn=item['NISN'][:35]
                if db.execute('SELECT 1 FROM students WHERE (? != "" AND nisn=?) OR (? != "" AND nipd=?)',
                              (nisn,nisn,nipd,nipd)).fetchone():
                    skipped+=1;continue
                klass=class_id(db,item['KELAS'])
                db.execute('''INSERT INTO students(nipd,nisn,name,gender,class_id,qr_token,joined_on)
                   VALUES (?,?,?,?,?,?,?)''',(nipd,nisn,name,sex,klass,secrets.token_urlsafe(32),now_wib().date().isoformat()))
                inserted+=1
            log(db,user['id'],'STUDENT_IMPORT',f'{inserted} masuk, {skipped} duplikat',client_ip(request))
        notice(request,f'Impor selesai: {inserted} siswa baru, {skipped} dilewati karena duplikat.')
    except Exception as exc: notice(request,f'Impor siswa dibatalkan: {exc}','error')
    return goto('/students')

@app.get('/students/template')
def students_template(request:Request):
    get_user(request)
    wb=Workbook();ws=wb.active;ws.title='IMPORT SISWA'
    ws.append(['NIPD','NISN','NAMA','JENIS KELAMIN','KELAS'])
    ws.append(['1001','1234567890','Contoh Siswa','L','VII A'])
    for c in 'AB':ws.column_dimensions[c].width=19
    ws.column_dimensions['C'].width=36;ws.column_dimensions['D'].width=23;ws.column_dimensions['E'].width=18
    buffer=io.BytesIO();wb.save(buffer);buffer.seek(0)
    return StreamingResponse(buffer,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':'attachment; filename="template_import_siswa.xlsx"'})

@app.get('/students/{student_id}/edit')
def edit_student_page(request:Request,student_id:int):
    user=get_user(request,admin=True)
    with connect() as db:
        student=db.execute('''SELECT s.*,c.name AS class_name FROM students s JOIN classes c ON c.id=s.class_id
           WHERE s.id=?''',(student_id,)).fetchone()
        classes=db.execute('SELECT * FROM classes ORDER BY name').fetchall()
    if not student: raise HTTPException(404,'Siswa tidak ditemukan.')
    return render(request,'student_edit',user=user,student=student,classes=classes)

@app.post('/students/{student_id}/edit')
async def edit_student_save(request:Request,student_id:int):
    user=get_user(request,admin=True);form=submitted_form(request,await request.form())
    try:
        name=val_name(form.get('name',''))
        gender=str(form.get('gender','')).upper()
        if gender not in ('L','P'): raise ValueError('Pilih jenis kelamin yang benar.')
        nisn=str(form.get('nisn','')).strip()[:35]
        nipd=str(form.get('nipd','')).strip()[:35]
        with connect() as db:
            if not db.execute('SELECT id FROM students WHERE id=?',(student_id,)).fetchone():
                raise ValueError('Siswa tidak ada.')
            duplicate=db.execute('''SELECT 1 FROM students WHERE id != ? AND
                ((? != '' AND nisn=?) OR (? != '' AND nipd=?))''',
                (student_id,nisn,nisn,nipd,nipd)).fetchone()
            if duplicate: raise ValueError('NIPD atau NISN sudah dipakai siswa lain.')
            cls=class_id(db,form.get('class_name',''),auto_create=False)
            db.execute('''UPDATE students SET name=?,gender=?,nipd=?,nisn=?,class_id=? WHERE id=?''',
                       (name,gender,nipd,nisn,cls,student_id))
            log(db,user['id'],'STUDENT_EDIT',f'{student_id}: {name}',client_ip(request))
        notice(request,'Data siswa berhasil diperbarui.')
        return goto('/students')
    except (ValueError,sqlite3.Error) as exc:
        notice(request,str(exc),'error')
        return goto(f'/students/{student_id}/edit')

@app.post('/students/{student_id}/new-qr')
async def regenerate_qr(request:Request,student_id:int):
    user=get_user(request,admin=True);submitted_form(request,await request.form())
    with connect() as db:
        row=db.execute('SELECT id FROM students WHERE id=?',(student_id,)).fetchone()
        if not row: raise HTTPException(404,'Siswa tidak ditemukan.')
        db.execute('UPDATE students SET qr_token=? WHERE id=?',(secrets.token_urlsafe(32),student_id))
        log(db,user['id'],'STUDENT_QR_RESET',f'Siswa {student_id}',client_ip(request))
    notice(request,'QR baru dibuat. Kartu lama tidak lagi berlaku; cetak ulang ID Card.')
    return goto(f'/students/{student_id}/edit')

@app.post('/students/{student_id}/toggle')
async def student_toggle(request:Request,student_id:int):
    user=get_user(request,admin=True);submitted_form(request,await request.form())
    with connect() as db:
        db.execute('UPDATE students SET active=1-active WHERE id=?',(student_id,))
        log(db,user['id'],'STUDENT_TOGGLE',f'ID {student_id}',client_ip(request))
    notice(request,'Status keaktifan siswa diperbarui.')
    return goto('/students')

@app.get('/cards')
def cards_page(request:Request,kelas:str=''):
    user=get_user(request)
    with connect() as db:
        rows=students_query(db,kelas)
        classes=db.execute('SELECT * FROM classes WHERE active=1 ORDER BY name').fetchall()
        opts=settings(db)
    return render(request,'cards',user=user,students=rows,classes=classes,kelas=kelas,settings=opts)

@app.get('/students/{student_id}/card')
def one_card(request:Request,student_id:int):
    user=get_user(request)
    with connect() as db:
        student=db.execute('SELECT s.*,c.name AS class_name FROM students s JOIN classes c ON c.id=s.class_id WHERE s.id=?',(student_id,)).fetchone()
        opts=settings(db)
    if not student: raise HTTPException(404,'Siswa tidak ada.')
    return render(request,'cards',user=user,students=[student],classes=[],kelas='',settings=opts)

@app.get('/students/{student_id}/qr.png')
def student_qr(request:Request,student_id:int):
    get_user(request)
    with connect() as db: row=db.execute('SELECT qr_token FROM students WHERE id=?',(student_id,)).fetchone()
    if not row: raise HTTPException(404,'Siswa tidak ada.')
    img=qrcode.make('SANJARA:'+row['qr_token'],box_size=8,border=3)
    buf=io.BytesIO();img.save(buf,format='PNG');buf.seek(0)
    return StreamingResponse(buf,media_type='image/png',headers={'Cache-Control':'no-store'})

@app.get('/scan')
def scan_page(request:Request):
    user=get_user(request)
    with connect() as db:opts=settings(db)
    return render(request,'scan',user=user,settings=opts)

@app.post('/api/scan')
async def scan_submit(request:Request,payload:QRPayload):
    user=get_user(request,api=True)
    validate_csrf(request)
    lat,lon,accuracy=payload.latitude,payload.longitude,payload.accuracy
    if not all(map(math.isfinite,[lat,lon,accuracy])) or not(-90<=lat<=90 and -180<=lon<=180) or accuracy<0 or accuracy>100:
        raise HTTPException(422,'Akurasi GPS harus maksimal 100 meter.')
    token=payload.token.strip()
    if token.startswith('SANJARA:'):token=token.split(':',1)[1]
    at=now_wib();day=at.date().isoformat()
    with connect() as db:
        cfg=settings(db)
        if not cfg['latitude'] or not cfg['longitude']:
            raise HTTPException(409,'Koordinat sekolah belum ditentukan oleh admin.')
        radius=float(cfg['radius_m'])
        distance=distance_m(lat,lon,float(cfg['latitude']),float(cfg['longitude']))
        if distance>radius:
            raise HTTPException(403,f'Lokasi di luar area sekolah (sekitar {round(distance)} m dari titik sekolah).')
        if not school_day(db,day,cfg): raise HTTPException(409,'Hari ini bukan hari sekolah.')
        if at.time()>=time.fromisoformat(cfg['closing']):raise HTTPException(409,'Absensi hari ini sudah ditutup.')
        student=db.execute('''SELECT s.*,c.name AS class_name FROM students s JOIN classes c ON c.id=s.class_id
                WHERE s.qr_token=? AND s.active=1''',(token,)).fetchone()
        if not student:raise HTTPException(404,'Kode QR tidak dikenal atau siswa tidak aktif.')
        existing=db.execute('SELECT * FROM attendance WHERE student_id=? AND day=?',(student['id'],day)).fetchone()
        if existing: raise HTTPException(409,f'{student["name"]} sudah tercatat pada hari ini.')
        status,late=late_status(at,cfg['cutoff'])
        try:
            db.execute('''INSERT INTO attendance(student_id,day,status,scanned_at,late_seconds,source,operator_id,created_at)
                VALUES (?,?,?,?,?,?,?,?)''',(student['id'],day,status,at.isoformat(),late,'QR',user['id'],at.isoformat()))
            log(db,user['id'],'SCAN_QR',f'{student["name"]} {status} {at.strftime("%H:%M:%S")}',client_ip(request))
        except sqlite3.IntegrityError: raise HTTPException(409,'Absensi sudah tersimpan hari ini.')
    return JSONResponse({'ok':True,'student':student['name'],'class_name':student['class_name'],
        'nisn':student['nisn'],'time':at.strftime('%H:%M:%S'),'status':status,
        'late_seconds':late,'distance_m':round(distance),'day':day})

@app.get('/leave')
def leave_page(request:Request):
    user=get_user(request)
    with connect() as db:
        students=students_query(db)
        rows=db.execute('''SELECT l.*,s.name,c.name AS class_name,u.display_name AS sender
          FROM leave_requests l JOIN students s ON s.id=l.student_id JOIN classes c ON c.id=s.class_id
          JOIN users u ON u.id=l.submitted_by ORDER BY l.id DESC LIMIT 250''').fetchall()
    return render(request,'leave',user=user,students=students,requests=rows)

@app.post('/leave/add')
async def leave_add(request:Request):
    user=get_user(request);form=submitted_form(request,await request.form())
    path=None
    try:
        sid=int(form.get('student_id'))
        day=parse_day(form.get('day',''))
        kind=str(form.get('kind','')).upper()
        reason=str(form.get('reason','')).strip()
        custom=str(form.get('custom_reason','')).strip()
        if kind not in ('SAKIT','IJIN'): raise ValueError('Pilih Sakit atau Ijin.')
        if reason=='Lainnya': reason=val_name(custom,250)
        elif not reason: raise ValueError('Alasan harus dipilih atau ditulis.')
        elif len(reason)>250: raise ValueError('Alasan maksimal 250 karakter.')
        upload=form.get('letter')
        if not upload or not hasattr(upload,'read') or not upload.filename:raise ValueError('Surat PDF/JPG/PNG wajib dilampirkan.')
        extension=Path(upload.filename).suffix.lower()
        if extension not in ('.pdf','.png','.jpg','.jpeg'):raise ValueError('Hanya file PDF/JPG/PNG yang diizinkan.')
        blob=await upload.read(8*1024*1024+1)
        if not blob or len(blob)>8*1024*1024: raise ValueError('Ukuran surat 1 byte hingga 8 MB.')
        valid=(extension=='.pdf' and blob.startswith(b'%PDF-')) or \
              (extension=='.png' and blob.startswith(b'\x89PNG\r\n\x1a\n')) or \
              (extension in ('.jpg','.jpeg') and blob.startswith(b'\xff\xd8\xff'))
        if not valid:raise ValueError('Isi file bukan PDF/JPG/PNG yang sah.')
        with connect() as db:
            if not db.execute('SELECT 1 FROM students WHERE id=? AND active=1',(sid,)).fetchone():
                raise ValueError('Siswa tidak aktif atau tidak ditemukan.')
            if db.execute('SELECT 1 FROM attendance WHERE student_id=? AND day=?',(sid,day)).fetchone():
                raise ValueError('Siswa sudah memiliki absensi pada tanggal tersebut.')
            if db.execute("SELECT 1 FROM leave_requests WHERE student_id=? AND day=? AND state='PENDING'",(sid,day)).fetchone():
                raise ValueError('Sudah ada permohonan yang menunggu persetujuan.')
            filename=secrets.token_hex(24)+extension
            path=LETTERS_DIR/filename
            path.write_bytes(blob)
            db.execute('''INSERT INTO leave_requests(student_id,day,kind,reason,filename,state,submitted_by,created_at)
                 VALUES (?,?,?,?,?,'PENDING',?,?)''',(sid,day,kind,reason,filename,user['id'],now_wib().isoformat()))
            log(db,user['id'],'LEAVE_SUBMIT',f'Siswa {sid} pada {day}',client_ip(request))
        notice(request,'Surat izin diterima dan menunggu persetujuan admin.')
    except Exception as exc:
        if path and path.exists():path.unlink()
        notice(request,str(exc),'error')
    return goto('/leave')

@app.post('/leave/{leave_id}/review')
async def leave_review(request:Request,leave_id:int):
    user=get_user(request,admin=True);form=submitted_form(request,await request.form())
    action=str(form.get('action','')).upper()
    if action not in ('APPROVED','REJECTED'):raise HTTPException(400,'Aksi tidak dikenal.')
    try:
        with connect() as db:
            row=db.execute('SELECT * FROM leave_requests WHERE id=?',(leave_id,)).fetchone()
            if not row:raise ValueError('Permohonan tidak ditemukan.')
            if row['state']!='PENDING':raise ValueError('Permohonan sudah diproses.')
            if action=='APPROVED':
                if db.execute('SELECT 1 FROM attendance WHERE student_id=? AND day=?',(row['student_id'],row['day'])).fetchone():
                    raise ValueError('Absensi siswa pada tanggal tersebut sudah ada.')
                db.execute('''INSERT INTO attendance(student_id,day,status,scanned_at,source,operator_id,created_at)
                    VALUES (?,?,?,NULL,'SURAT',?,?)''',
                    (row['student_id'],row['day'],row['kind'],user['id'],now_wib().isoformat()))
            db.execute('UPDATE leave_requests SET state=?,reviewed_by=?,reviewed_at=? WHERE id=?',
                       (action,user['id'],now_wib().isoformat(),leave_id))
            log(db,user['id'],'LEAVE_REVIEW',f'Permohonan {leave_id}: {action}',client_ip(request))
        notice(request,'Surat disetujui, rekap otomatis berubah.' if action=='APPROVED' else 'Surat izin ditolak.')
    except (ValueError,sqlite3.Error) as exc:notice(request,str(exc),'error')
    return goto('/leave')

@app.get('/leave/{leave_id}/letter')
def leave_letter(request:Request,leave_id:int):
    get_user(request)
    with connect() as db:row=db.execute('SELECT filename FROM leave_requests WHERE id=?',(leave_id,)).fetchone()
    if not row:raise HTTPException(404,'Surat tidak ada.')
    filename=Path(row['filename']).name
    path=LETTERS_DIR/filename
    if not path.is_file():raise HTTPException(404,'File surat hilang.')
    from fastapi.responses import FileResponse
    return FileResponse(str(path),filename='surat_izin'+path.suffix,media_type='application/octet-stream',headers={'Cache-Control':'no-store'})

@app.get('/reports')
def reports_page(request:Request,month:str|None=None,day:str|None=None,kelas:str=''):
    user=get_user(request)
    month=month or now_wib().strftime('%Y-%m')
    try:
        parse_month(month);day=parse_day(day or now_wib().date().isoformat())
        if not day.startswith(month):day=month+'-01'
    except ValueError as exc:raise HTTPException(400,str(exc))
    with connect() as db:
        rows=attendance_report(db,month,day,kelas)
        classes=db.execute('SELECT * FROM classes ORDER BY name').fetchall()
    return render(request,'reports',user=user,rows=rows,classes=classes,month=month,day=day,kelas=kelas)

@app.get('/reports/export.xlsx')
def export_xlsx(request:Request,month:str|None=None,day:str|None=None,kelas:str=''):
    get_user(request)
    month=month or now_wib().strftime('%Y-%m')
    try:
        parse_month(month);day=parse_day(day or now_wib().date().isoformat())
        if not day.startswith(month):day=month+'-01'
    except ValueError as exc:raise HTTPException(400,str(exc))
    with connect() as db:buffer=make_report(db,month,day,kelas)
    filename=f'SANJARA_REKAP_{month}_{day}.xlsx'
    return StreamingResponse(buffer,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':f'attachment; filename="{filename}"'})

@app.get('/settings')
def settings_page(request:Request):
    user=get_user(request,admin=True)
    with connect() as db:
        cfg=settings(db)
        holidays=db.execute('SELECT * FROM holidays ORDER BY day DESC LIMIT 80').fetchall()
        logs=db.execute('''SELECT l.*,u.display_name AS actor FROM audit_logs l LEFT JOIN users u ON u.id=l.actor_id
           ORDER BY l.id DESC LIMIT 15''').fetchall()
    return render(request,'settings',user=user,settings=cfg,holidays=holidays,logs=logs,drive_ready=drive.configured())

@app.post('/settings/save')
async def save_settings(request:Request):
    user=get_user(request,admin=True);form=submitted_form(request,await request.form())
    try:
        name=val_name(form.get('school_name',''),140)
        address=val_name(form.get('school_address',''),220)
        lat=float(form.get('latitude',''));lon=float(form.get('longitude',''))
        radius=int(form.get('radius_m',''))
        cutoff=time.fromisoformat(str(form.get('cutoff','')))
        closing=time.fromisoformat(str(form.get('closing','')))
        workdays=[v for v in form.getlist('workdays') if v in list('0123456')]
        if not(-90<=lat<=90 and -180<=lon<=180 and 20<=radius<=2000):raise ValueError('Koordinat atau radius tidak valid.')
        if cutoff>=closing:raise ValueError('Jam penutupan harus setelah batas waktu hadir.')
        if not workdays:raise ValueError('Minimal pilih satu hari sekolah.')
        config={'school_name':name,'school_address':address,'latitude':str(lat),'longitude':str(lon),
                'radius_m':str(radius),'cutoff':cutoff.strftime('%H:%M:%S'),'closing':closing.strftime('%H:%M:%S'),
                'workdays':','.join(sorted(set(workdays)))}
        with connect() as db:
            for k,v in config.items():set_setting(db,k,v)
            log(db,user['id'],'SETTINGS_SAVE',f'Radius {radius} m / Batas {cutoff}',client_ip(request))
        notice(request,'Pengaturan sekolah berhasil disimpan.')
    except (ValueError,TypeError) as exc:notice(request,str(exc),'error')
    return goto('/settings')

@app.post('/settings/holiday')
async def holiday_add(request:Request):
    user=get_user(request,admin=True);form=submitted_form(request,await request.form())
    try:
        day=parse_day(form.get('day',''))
        desc=val_name(form.get('description',''),180)
        with connect() as db:
            db.execute('INSERT OR REPLACE INTO holidays(day,description) VALUES (?,?)',(day,desc))
            log(db,user['id'],'HOLIDAY_ADD',day,client_ip(request))
        notice(request,'Hari libur dicatat.')
    except ValueError as exc:notice(request,str(exc),'error')
    return goto('/settings')

@app.post('/settings/holiday/{day}/delete')
async def holiday_delete(request:Request,day:str):
    user=get_user(request,admin=True);submitted_form(request,await request.form())
    try:
        day=parse_day(day)
        with connect() as db:
            db.execute('DELETE FROM holidays WHERE day=?',(day,))
            log(db,user['id'],'HOLIDAY_DELETE',day,client_ip(request))
        notice(request,'Hari libur dihapus.')
    except ValueError as exc:notice(request,str(exc),'error')
    return goto('/settings')

@app.get('/users')
def users_page(request:Request):
    user=get_user(request,admin=True)
    with connect() as db:rows=db.execute('SELECT id,username,display_name,role,active,created_at FROM users ORDER BY role,display_name').fetchall()
    return render(request,'users',user=user,users=rows)

@app.post('/users/add')
async def user_add(request:Request):
    admin=get_user(request,admin=True);form=submitted_form(request,await request.form())
    try:
        name=val_name(form.get('display_name',''))
        username=val_name(form.get('username',''),45)
        pwd=str(form.get('password',''))
        role=str(form.get('role','')).upper()
        if len(pwd)<10:raise ValueError('Password minimal 10 karakter.')
        if role not in ('ADMIN','PETUGAS'):raise ValueError('Peran tidak valid.')
        with connect() as db:
            db.execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES (?,?,?,?,?)',
                       (username,name,password_hash(pwd),role,now_wib().isoformat()))
            log(db,admin['id'],'USER_ADD',username,client_ip(request))
        notice(request,'Akun petugas berhasil dibuat.')
    except (ValueError,sqlite3.IntegrityError) as exc: notice(request,str(exc),'error')
    return goto('/users')

@app.post('/users/{uid}/toggle')
async def user_toggle(request:Request,uid:int):
    admin=get_user(request,admin=True);submitted_form(request,await request.form())
    if uid==admin['id']:
        notice(request,'Tidak dapat menonaktifkan akun yang sedang dipakai.','error')
        return goto('/users')
    with connect() as db:
        row=db.execute('SELECT role,active FROM users WHERE id=?',(uid,)).fetchone()
        if not row:raise HTTPException(404,'Pengguna tidak ada.')
        if row['role']=='ADMIN' and row['active']:
            count=db.execute("SELECT COUNT(*) FROM users WHERE role='ADMIN' AND active=1").fetchone()[0]
            if count<2:
                notice(request,'Minimal satu administrator harus aktif.','error')
                return goto('/users')
        db.execute('UPDATE users SET active=1-active WHERE id=?',(uid,))
        log(db,admin['id'],'USER_TOGGLE',f'User {uid}',client_ip(request))
    notice(request,'Status petugas diperbarui.')
    return goto('/users')

@app.get('/profile')
def profile_page(request:Request):
    user=get_user(request)
    return render(request,'profile',user=user)

@app.post('/profile/password')
async def profile_password(request:Request):
    user=get_user(request);form=submitted_form(request,await request.form())
    current=str(form.get('current_password',''))
    new=str(form.get('new_password',''))
    confirm=str(form.get('confirm_password',''))
    if len(new)<10 or new!=confirm:
        notice(request,'Password baru minimal 10 karakter dan konfirmasi harus sama.','error')
        return goto('/profile')
    with connect() as db:
        account=db.execute('SELECT password_hash FROM users WHERE id=?',(user['id'],)).fetchone()
        if not account or not check_password(current,account['password_hash']):
            notice(request,'Kata sandi lama tidak sesuai.','error')
            return goto('/profile')
        db.execute('UPDATE users SET password_hash=? WHERE id=?',(password_hash(new),user['id']))
        log(db,user['id'],'PASSWORD_CHANGE','Petugas mengganti password',client_ip(request))
    request.session.clear()
    notice(request,'Kata sandi berhasil diganti. Silakan login kembali.')
    return goto('/login')

@app.post('/classes/{klass_id}/rename')
async def rename_class(request:Request,klass_id:int):
    user=get_user(request,admin=True);form=submitted_form(request,await request.form())
    try:
        name=val_name(form.get('name',''),45)
        with connect() as db:
            row=db.execute('SELECT id FROM classes WHERE id=?',(klass_id,)).fetchone()
            if not row: raise ValueError('Kelas tidak ditemukan.')
            db.execute('UPDATE classes SET name=? WHERE id=?',(name,klass_id))
            log(db,user['id'],'CLASS_RENAME',f'{klass_id} => {name}',client_ip(request))
        notice(request,'Nama kelas berhasil diperbarui.')
    except (ValueError,sqlite3.IntegrityError) as exc: notice(request,str(exc),'error')
    return goto('/classes')

@app.get('/backup/download')
def download_backup(request:Request):
    admin=get_user(request,admin=True)
    data=make_backup()
    return StreamingResponse(data,media_type='application/zip',headers={
        'Content-Disposition':f'attachment; filename="SANJARA_BACKUP_{now_wib().strftime("%Y%m%d_%H%M%S")}.zip"'})

@app.get('/drive/connect')
def drive_connect(request:Request):
    get_user(request,admin=True)
    if not drive.configured():
        notice(request,'Isi GDRIVE_CLIENT_ID dan GDRIVE_CLIENT_SECRET dahulu.','error');return goto('/settings')
    state=secrets.token_urlsafe(32)
    request.session['google_state']=state
    redirect_uri=os.getenv('GDRIVE_REDIRECT_URI') or str(request.url_for('drive_callback'))
    return RedirectResponse(drive.authorize_url(state,redirect_uri))

@app.get('/drive/callback')
def drive_callback(request:Request,code:str='',state:str='',error:str=''):
    user=get_user(request,admin=True)
    expected=request.session.pop('google_state','')
    if not expected or not secrets.compare_digest(expected,state):raise HTTPException(403,'Status OAuth tidak valid.')
    if error:notice(request,'Google Drive tidak diizinkan: '+error,'error');return goto('/settings')
    try:
        redirect_uri=os.getenv('GDRIVE_REDIRECT_URI') or str(request.url_for('drive_callback'))
        token=drive.exchange_code(code,redirect_uri)
        with connect() as db:
            set_setting(db,'drive_refresh_token_enc',encrypt(token))
            set_setting(db,'drive_folder_id','')
            log(db,user['id'],'DRIVE_CONNECT','Google Drive dihubungkan',client_ip(request))
        notice(request,'Google Drive berhasil dihubungkan.')
    except Exception as exc:notice(request,'Gagal menghubungkan Google Drive: '+str(exc),'error')
    return goto('/settings')

@app.post('/drive/disconnect')
async def drive_disconnect(request:Request):
    user=get_user(request,admin=True);submitted_form(request,await request.form())
    with connect() as db:
        set_setting(db,'drive_refresh_token_enc','');set_setting(db,'drive_folder_id','')
        log(db,user['id'],'DRIVE_DISCONNECT','Token dihapus dari aplikasi',client_ip(request))
    notice(request,'Koneksi Google Drive diputus dari aplikasi.')
    return goto('/settings')

@app.post('/backup/drive')
async def drive_backup(request:Request):
    user=get_user(request,admin=True);submitted_form(request,await request.form())
    try:
        archive=make_backup()
        filename='SANJARA_BACKUP_'+now_wib().strftime('%Y%m%d_%H%M%S')+'.zip'
        with connect() as db:
            uploaded=drive.upload_backup(db,archive,filename)
            log(db,user['id'],'DRIVE_BACKUP',uploaded.get('name',filename),client_ip(request))
        notice(request,'Backup berhasil diunggah ke Google Drive: '+uploaded.get('name',filename))
    except Exception as exc:
        notice(request,'Backup ke Google Drive gagal. Periksa koneksi/izin OAuth: '+str(exc)[:190],'error')
    return goto('/settings')
