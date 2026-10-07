# SANJARA HADIR — School Edition 2.0

**Aplikasi absensi QR siswa SMP SSA Negeri Jenggrong Ranuyoso**. Proyek ini dibangun ulang dengan arsitektur FastAPI + SQLite lokal yang persisten, halaman HTML responsif, dan hak akses berbasis peran. **Source code ini belum diunggah ke GitHub.**

## 1. Apa saja fiturnya?

- Dashboard real-time berdasarkan tanggal, nama murid, NIPD/NISN, dan kelas.
- Absensi QR **langsung tersimpan begitu QR terbaca**: kamera + GPS browser milik *petugas sekolah*. QR ID Card menyimpan token acak unik, bukan NISN.
- Geofence/radius diatur admin (20–2.000 m). Sistem menolak scan dari luar koordinat sekolah atau akurasi GPS >100 m. Petugas harus memberi izin kamera dan lokasi. **GPS browser tidak dapat dijamin anti-spoofing; scan perlu diawasi petugas.**
- Batas hadir **07:00:00 WIB**: sesudahnya `TERLAMBAT`, tetapi tetap hadir. Jam dan detik scan dicatat menggunakan waktu **server Asia/Jakarta**; batas dan jam tutup bisa diatur.
- Scan siswa yang sama maksimal sekali per hari. Absensi ditutup ketika jam penutupan tercapai dan tidak dapat dilakukan pada hari libur/bukan hari sekolah.
- CRUD sederhana siswa (tambah/nonaktifkan), import **siswa Excel** (`NIPD,NISN,NAMA,JENIS KELAMIN,KELAS`), import **kelas Excel/CSV** (`KELAS`), ID Card dengan QR dan mode cetak.
- Permohonan Sakit/Ijin dilengkapi surat PDF/PNG/JPG, pilihan alasan dan **alasan custom**, diverifikasi administrator. Permohonan disetujui otomatis masuk rekap.
- Laporan harian dan bulanan, Excel lima sheet: `REKAP` (No, NIPD, NISN, NAMA, JENIS KELAMIN, KELAS, status harian SAKIT/IJIN/ALPA, JUMLAH bulanan SAKIT/IJIN/ALPA), `DETAIL WAKTU`, `HARIAN`, `PETUNJUK`, `KALENDER LIBUR`.
- Hak akses: **ADMIN** (seluruh fitur), **PETUGAS** (scan, lihat siswa/kelas/kartu/rekap, buat pengajuan). Semua akun dapat mengganti password sendiri; admin juga dapat mengedit identitas siswa, merotasi QR jika hilang/bocor, dan mengganti nama kelas.
- Audit aktivitas, password PBKDF2, sesi HTTP-only, CSRF untuk seluruh penulisan, upload privat dengan validasi isi berkas, backup ZIP snapshot konsisten.
- **Google Drive OAuth opsional:** admin menghubungkan akunnya, aplikasi membuat folder privat `SANJARA HADIR - Backup` di Drive admin dan bisa unggah backup manual; script tambahan dapat dijadwalkan via cron di server; arsip dapat dipulihkan lewat skrip restore terpisah ketika server dihentikan.

## 2. Jalankan di Windows (paling mudah)

Syarat: Python **3.11 atau lebih baru** terpasang di komputer.

**Cara cepat:** ekstrak ZIP, klik dua kali **`INSTAL_WINDOWS.bat`**. Installer memasang paket dan meminta username/password admin pribadi melalui terminal (tanpa password bawaan), sekaligus membuat `SECRET_KEY` random. Setelah pemasangan pertama, cukup klik **`JALANKAN_WINDOWS.bat`** untuk menjalankan aplikasi lagi. Aplikasi terbuka di `http://localhost:8000`. *Pastikan internet tersedia saat pemasangan dependensi.*

**Cara manual (opsional):**

1. Ekstrak paket ZIP menjadi folder `SANJARA_HADIR`.
2. Buka Terminal/PowerShell di folder itu.
3. Buat lingkungan virtual dan install dependensi:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. Jalankan `python -m scripts.setup` untuk membuat `.env` yang aman secara interaktif; alternatifnya salin `.env.example` menjadi `.env` dan ganti **`SECRET_KEY` dan `ADMIN_PASSWORD`**. Jangan unggah `.env` ke publik. Kata sandi admin minimal 10 karakter.
5. Jalankan aplikasi:

   ```powershell
   python start.py
   ```
6. Buka **http://localhost:8000**, login dengan username yang disetel (default `admin`) dan password dari `.env`.
7. Masuk **Pengaturan & Backup → isi koordinat GPS sekolah**; tanpa koordinat, scan QR otomatis ditolak.
8. Tambahkan kelas dan siswa / impor file Excel; buka **ID Card** untuk cetak kartu QR.

**Cara melihat website dari HP:** gunakan alamat HTTPS pada server yang bisa diakses HP. Akses HTTP lewat IP lokal biasa tidak cukup untuk izin kamera/geolokasi di banyak browser. Fitur scan dapat diuji di browser komputer pada `localhost` jika memiliki kamera dan GPS terdeteksi.

## 3. Jalankan via Docker

```sh
cp .env.example .env
# edit .env: ADMIN_PASSWORD, SECRET_KEY

docker compose up --build -d
```

Kunjungi http://localhost:8000. Berkas database dan surat tersimpan di `./data` (host), tidak hilang hanya karena container di-restart. Gunakan HTTPS reverse-proxy (mis. Caddy/NGINX) dan set `SESSION_SECURE=1` untuk pemakaian resmi. Docker worker **satu** untuk menjaga operasi SQLite lebih terkontrol. Pastikan server memiliki jadwal backup dan ruang disk yang cukup.

## 4. Konfigurasi lokasi dan jam

Pengaturan menyediakan koordinat lintang/bujur, radius meter, batas hadir `07:00:00` WIB, penutupan `15:00:00` WIB, hari sekolah Senin–Sabtu (default), dan kalender hari libur. Untuk titik sekolah, ambil koordinat dari peta langsung pada lokasi gerbang/ruang scan, bukan menebak lokasi.

**Contoh:** pukul `07:00:00` tepat waktu; `07:00:01` terlambat 1 detik; `07:12:30` terlambat 12 menit 30 detik. Setelah jam tutup, jika tidak ada kehadiran/surat disetujui, status menjadi ALPA untuk hari sekolah. Status baru dihitung sejak tanggal siswa didaftarkan.

## 5. Format impor

- Siswa, Excel: `NIPD | NISN | NAMA | JENIS KELAMIN | KELAS`. Jenis kelamin `L` / `P` atau `Laki-laki` / `Perempuan`. **Atur kolom NIPD/NISN sebagai Text di Excel sebelum memasukkan nomor yang diawali nol**. Data duplikat NIPD/NISN yang sudah ada dilewati.
- Kelas, Excel/CSV: satu kolom `KELAS`. Kelas yang sudah ada tidak ditambahkan lagi.
- Halaman `Data Siswa` dan `Data Kelas` menyediakan unduhan template impor.

## 6. Google Drive — koneksi resmi via admin

Integrasi sudah diimplementasikan menggunakan OAuth Google Drive API. Agar aktif, Anda perlu membuat kredensial OAuth Web Application milik sekolah di [Google Cloud Console](https://console.cloud.google.com/apis/credentials):

1. Buat proyek Google Cloud, aktifkan **Google Drive API**, konfigurasi OAuth consent screen (pengguna internal atau test user sesuai kebijakan Google).
2. Buat `OAuth Client ID` jenis **Web application** dan set *Authorized redirect URI* misalnya `https://absensi-sekolah.example/drive/callback`. Untuk pengujian `http://localhost:8000/drive/callback` juga dapat digunakan sebagai URI terdaftar.
3. Di `.env` tetapkan `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`, `GDRIVE_REDIRECT_URI`, dan `SECRET_KEY` yang permanen.
4. Masuk sebagai admin, buka **Pengaturan & Backup → Hubungkan Google Drive**; pilih akun Google dan setujui scope `drive.file`. Aplikasi menciptakan folder backupnya sendiri dan tidak perlu akses penuh ke Drive.
5. Klik **Backup ke Google Drive sekarang**. Token refresh disimpan terenkripsi di database dengan kunci turunan `SECRET_KEY`. **Jangan mengganti `SECRET_KEY`** tanpa migrasi token / menghubungkan ulang Drive.
6. Untuk backup otomatis harian, jalankan `python -m scripts.backup_to_drive` via *Task Scheduler* / `cron` pada server yang selalu menyala, setelah koneksi Drive berhasil.

**Catatan:** tanpa kredensial Google yang valid dan akses internet, backup Drive tidak dapat diuji secara live. Mode backup ZIP lokal tetap tersedia. Simpan arsip yang berisi informasi murid di tempat privat. Memutus koneksi hanya menghapus token lokal, tidak otomatis menghapus backup di Google Drive.

### Pemulihan cadangan (jika server rusak atau pindah server)

**Hentikan server sebelum memulihkan.** Simpan file ZIP cadangan di komputer atau server yang memiliki akses privat. Jalankan:

```sh
python -m scripts.restore_backup --archive /lokasi/SANJARA_BACKUP.zip --i-have-stopped-server
```

Skrip memeriksa integritas SQLite, memulihkan database dan lampiran surat, serta menyimpan salinan database sebelumnya untuk keamanan. **Pemulihan menimpa data terbaru setelah tanggal backup**; lakukan dengan sadar dan tutup aplikasi untuk mencegah konflik WAL.

## 7. Mengapa belum langsung Vercel?

Aplikasi baru ini mengandalkan SQLite dan arsip surat di volume server **persisten**. **Jangan langsung deploy ke Vercel serverless dengan SQLite lokal**: penyimpanan sementara dapat hilang. Untuk Vercel produksi harus terlebih dahulu migrasi ke **database terkelola (mis. PostgreSQL)** dan **object storage privat** untuk surat izin. Alternatif awal yang stabil: Docker di VPS/sekolah dengan volume persisten + HTTPS dan backup berkala. Mengunggah source ke repository GitHub baru **bukan** bagian dari paket saat ini dan akan dilakukan hanya atas arahan pengguna.

## 8. Pengujian

```sh
pytest -q
```

Test mencakup akses, impor, batas jam, geofence, scan otomatis, duplikasi, surat izin, rekap Excel, dan backup. Tes API tidak bisa menggantikan uji langsung kamera/GPS pada ponsel di area sekolah dan uji Google OAuth live.

## 9. Keamanan sebelum digunakan sungguhan

Gunakan username unik dan kata sandi admin kuat; selalu aktifkan HTTPS; simpan `.env` dan folder `data/` **di luar repository publik**; batasi akses ke operator; backup otomatis dan uji pemulihan; awasi perangkat scan (QR dapat difoto/disalin); siapkan persetujuan/pemberitahuan privasi siswa dan surat sesuai kebijakan sekolah. Login dibatasi 10 percobaan salah per 15 menit per IP+username. Pakai `SESSION_SECURE=1` bila situs sudah HTTPS. Untuk banyak petugas dan kebutuhan skala besar, rencanakan migrasi database terkelola serta penguatan keamanan/sesi/monitoring.

### Struktur proyek

```
SANJARA_HADIR/
├── app/
│   ├── main.py        # FastAPI routes & tampilan
│   ├── db.py          # database dan transaksi
│   ├── services.py    # aturan GPS, tanggal, status
│   ├── reports.py     # ekspor Excel
│   ├── security.py    # autentikasi dan enkripsi
│   ├── backup.py      # ZIP snapshot
│   ├── drive.py       # Google OAuth dan upload backup
│   ├── templates/     # UI HTML responsif
│   └── static/        # CSS, JS, ikon
├── scripts/backup_to_drive.py dan restore_backup.py
├── tests/test_app.py
├── .env.example
├── INSTAL_WINDOWS.bat / JALANKAN_WINDOWS.bat
├── start.py
├── requirements.txt
├── Dockerfile
└── compose.yaml
```

**Versi ini dibuat dari awal, bukan copy-paste source proyek lama. Tidak ada tindakan push atau perubahan repository GitHub.**
