"""Lapisan SQLite persisten, transaksi, dan skema data."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_VERCEL = bool(os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV'))
# Vercel Functions have a read-only deployment filesystem. When no external
# persistent data directory is configured, use /tmp only so the application
# can boot for preview/testing. /tmp is ephemeral and MUST NOT be trusted for
# official attendance records.
default_data_dir = '/tmp/sanjara-hadir' if IS_VERCEL else str(ROOT / 'data')
DATA_DIR = Path(os.environ.get('DATA_DIR', default_data_dir)).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / 'sanjara.sqlite3'
LETTERS_DIR = DATA_DIR / 'letters'
LETTERS_DIR.mkdir(parents=True, exist_ok=True)

@contextmanager
def connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=25)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=10000')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('ADMIN','PETUGAS')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS classes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS students (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nipd TEXT NOT NULL DEFAULT '',
  nisn TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  gender TEXT NOT NULL CHECK(gender IN ('L','P')),
  class_id INTEGER NOT NULL REFERENCES classes(id),
  qr_token TEXT NOT NULL UNIQUE,
  joined_on TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS students_class_idx ON students(class_id);
CREATE INDEX IF NOT EXISTS students_nisn_idx ON students(nisn);
CREATE INDEX IF NOT EXISTS students_nipd_idx ON students(nipd);
CREATE TABLE IF NOT EXISTS attendance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES students(id),
  day TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('HADIR','TERLAMBAT','SAKIT','IJIN')),
  scanned_at TEXT,
  late_seconds INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL CHECK(source IN ('QR','SURAT','KOREKSI')),
  operator_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  UNIQUE(student_id, day)
);
CREATE INDEX IF NOT EXISTS attendance_day_idx ON attendance(day);
CREATE TABLE IF NOT EXISTS leave_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES students(id),
  day TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('SAKIT','IJIN')),
  reason TEXT NOT NULL,
  filename TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('PENDING','APPROVED','REJECTED')),
  submitted_by INTEGER NOT NULL REFERENCES users(id),
  reviewed_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS leave_day_idx ON leave_requests(day);
CREATE TABLE IF NOT EXISTS holidays (
  day TEXT PRIMARY KEY,
  description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ip TEXT NOT NULL,
  username TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS login_failure_idx ON login_failures(ip,username,created_at);
CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
'''
DEFAULTS = {
    'school_name':'SMP SSA Negeri Jenggrong Ranuyoso',
    'school_address':'Ranuyoso, Lumajang, Jawa Timur',
    'latitude':'', 'longitude':'', 'radius_m':'150',
    'cutoff':'07:00:00', 'closing':'15:00:00',
    'workdays':'0,1,2,3,4,5',
    'drive_folder_id':'', 'drive_refresh_token_enc':'',
}

def init_db():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
        for key, value in DEFAULTS.items():
            db.execute('INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)', (key, value))

def settings(db):
    return {r['key']:r['value'] for r in db.execute('SELECT key,value FROM settings')}

def set_setting(db, key, value):
    db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))

def log(db, actor, action, detail='', ip=''):
    from .services import now_wib
    db.execute('INSERT INTO audit_logs(actor_id,action,detail,ip,created_at) VALUES (?,?,?,?,?)',
               (actor,action,str(detail)[:500],str(ip)[:90],now_wib().isoformat()))
