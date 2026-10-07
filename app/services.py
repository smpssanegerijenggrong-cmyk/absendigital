"""Aturan sekolah: jam WIB, geofence, status, dan rekap."""
from datetime import date, datetime, time
from calendar import monthrange
from zoneinfo import ZoneInfo
import math

WIB = ZoneInfo('Asia/Jakarta')

def now_wib(): return datetime.now(WIB)

def parse_day(value):
    try: return date.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError): raise ValueError('Tanggal tidak valid.')

def parse_month(value):
    try:
        year,month=map(int,str(value).split('-'))
        if not (2000 <= year <= 2100 and 1 <= month <= 12): raise ValueError()
        return [date(year,month,d).isoformat() for d in range(1,monthrange(year,month)[1]+1)]
    except (TypeError,ValueError): raise ValueError('Bulan tidak valid.')

def school_day(db,day,options):
    if date.fromisoformat(day).weekday() not in {int(v) for v in options['workdays'].split(',') if v.isdigit()}:
        return False
    return db.execute('SELECT 1 FROM holidays WHERE day=?',(day,)).fetchone() is None

def late_status(at, cutoff):
    limit=datetime.combine(at.date(),time.fromisoformat(cutoff),tzinfo=WIB)
    seconds=math.ceil((at-limit).total_seconds()) if at>limit else 0
    return ('TERLAMBAT' if seconds else 'HADIR',seconds)

def distance_m(lat1,lon1,lat2,lon2):
    dl=math.radians(lon2-lon1)
    dlat=math.radians(lat2-lat1)
    a=math.sin(dlat/2)**2+math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dl/2)**2
    return 6371000 * 2 * math.asin(min(1,math.sqrt(a)))

def visible_status(db,student_id,day,options, joined_on=None, now=None):
    if joined_on and day < joined_on: return 'BELUM TERDAFTAR'
    row=db.execute('SELECT status FROM attendance WHERE student_id=? AND day=?',(student_id,day)).fetchone()
    if row: return row['status']
    if not school_day(db,day,options): return 'LIBUR'
    now=now or now_wib()
    today=now.date().isoformat()
    if day>today: return 'BELUM ABSEN'
    if day<today or (day==today and now.time() >= time.fromisoformat(options['closing'])):
        return 'ALPA'
    return 'BELUM ABSEN'

def students_query(db,klass='',q='',active_only=True):
    return db.execute('''SELECT s.*,c.name AS class_name FROM students s
        JOIN classes c ON c.id=s.class_id
        WHERE (?=0 OR s.active=1) AND (?='' OR c.name=?)
        AND (?='' OR s.name LIKE ? OR s.nisn LIKE ? OR s.nipd LIKE ?)
        ORDER BY c.name,s.name LIMIT 10000''',
        (1 if active_only else 0,klass,klass,q,*(['%'+q+'%']*3))).fetchall()

def attendance_report(db,month,selected_day,klass=''):
    days=parse_month(month)
    opts = __import__('app.db',fromlist=['settings']).settings(db)
    students = [s for s in students_query(db,klass) if s['joined_on'] <= days[-1]]
    current = now_wib().date().isoformat()
    results=[]
    for s in students:
        totals={'SAKIT':0,'IJIN':0,'ALPA':0,'HADIR':0,'TERLAMBAT':0}
        for day in days:
            if day<s['joined_on'] or day>current: continue
            status=visible_status(db,s['id'],day,opts,s['joined_on'])
            if status in totals: totals[status]+=1
        st=visible_status(db,s['id'],selected_day,opts,s['joined_on'])
        a=db.execute('SELECT scanned_at,late_seconds FROM attendance WHERE student_id=? AND day=?',(s['id'],selected_day)).fetchone()
        results.append(dict(student=dict(s),status=st,totals=totals,scanned_at=a['scanned_at'] if a else None,
                            late_seconds=a['late_seconds'] if a else 0))
    return results
