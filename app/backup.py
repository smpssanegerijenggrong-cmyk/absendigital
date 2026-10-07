"""Backup snapshot SQLite beserta lampiran privat."""
import io
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path
from .db import DB_PATH,LETTERS_DIR


def make_backup():
    memory=io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        target=Path(tmp)/'sanjara.sqlite3'
        with closing(sqlite3.connect(str(DB_PATH))) as original, closing(sqlite3.connect(str(target))) as snap:
            original.backup(snap)
        with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(target,'sanjara.sqlite3')
            for f in LETTERS_DIR.iterdir():
                if f.is_file() and not f.is_symlink(): z.write(f,'letters/'+f.name)
            z.writestr('PENTING.txt','Backup database dan lampiran SANJARA HADIR. Simpan secara privat. Berisi data pribadi murid.\n')
    memory.seek(0)
    return memory
