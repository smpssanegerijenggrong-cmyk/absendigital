"""Jadwalkan dengan cron pada server lokal untuk backup Google Drive berkala.
Contoh crontab (WIB server): 0 16 * * * cd /srv/SANJARA_HADIR && .venv/bin/python -m scripts.backup_to_drive
"""
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / '.env')
from app.db import connect,log
from app.backup import make_backup
from app.services import now_wib
from app.drive import upload_backup

def run():
    name='SANJARA_BACKUP_OTOMATIS_'+now_wib().strftime('%Y%m%d_%H%M%S')+'.zip'
    backup=make_backup()
    with connect() as db:
        result=upload_backup(db,backup,name)
        log(db,None,'DRIVE_BACKUP_SCHEDULED',result['name'])
    print('Backup ke Drive selesai:',result['name'])

if __name__ == '__main__':run()
