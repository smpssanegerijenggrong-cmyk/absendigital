"""Pulihkan backup ZIP di server yang SUDAH DIHENTIKAN.

python -m scripts.restore_backup --archive SANJARA_BACKUP.zip --i-have-stopped-server
"""
import argparse
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / '.env')
from app.db import DB_PATH,LETTERS_DIR,DATA_DIR
from app.services import now_wib


def restore(archive:Path):
    if not archive.is_file(): raise ValueError('Berkas ZIP tidak ditemukan.')
    with zipfile.ZipFile(archive) as z:
        files=set(z.namelist())
        if 'sanjara.sqlite3' not in files:raise ValueError('Backup tidak berisi database SANJARA.')
        for name in files:
            if not (name in ('sanjara.sqlite3','PENTING.txt') or (name.startswith('letters/') and '/' not in name[len('letters/'):])):
                raise ValueError('Arsip berisi path tidak diizinkan: '+name)
        with tempfile.TemporaryDirectory() as d:
            candidate=Path(d)/'restored.sqlite3'
            with z.open('sanjara.sqlite3') as source,candidate.open('wb') as target:
                shutil.copyfileobj(source,target)
            with closing(sqlite3.connect(candidate)) as conn:
                if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise ValueError('Database dalam backup rusak.')
                expected={r[0] for r in conn.execute('SELECT name FROM sqlite_master WHERE type="table"')}
                if not {'users','students','classes','attendance','settings','leave_requests'}.issubset(expected):
                    raise ValueError('Backup bukan database SANJARA yang kompatibel.')
            staged=Path(d)/'letters';staged.mkdir()
            for name in files:
                if not name.startswith('letters/') or name.endswith('/'):continue
                dest=staged/Path(name).name
                with z.open(name) as src,dest.open('wb') as target:shutil.copyfileobj(src,target)
            if DB_PATH.exists():
                safecopy=DATA_DIR/('before_restore_'+now_wib().strftime('%Y%m%d_%H%M%S')+'.sqlite3')
                shutil.copy2(DB_PATH,safecopy)
                print('Salinan keselamatan database lama:',safecopy)
            for suffix in ('-wal','-shm'):
                Path(str(DB_PATH)+suffix).unlink(missing_ok=True)
            for f in staged.iterdir():
                shutil.copy2(f,LETTERS_DIR/f.name)
            candidate.replace(DB_PATH)
    print('Pemulihan sukses. Jalankan kembali aplikasi, lalu periksa rekap dan surat.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Pulihkan database SANJARA dari backup. Hentikan server lebih dulu!')
    parser.add_argument('--archive',required=True,type=Path)
    parser.add_argument('--i-have-stopped-server',action='store_true')
    args=parser.parse_args()
    if not args.i_have_stopped_server:
        parser.error('WAJIB hentikan server dahulu dan tambahkan --i-have-stopped-server.')
    restore(args.archive)
