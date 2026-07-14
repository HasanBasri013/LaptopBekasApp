# LaptopBekasApp

Sistem Jual Beli Laptop Bekas — aplikasi web berbasis **Python (Flask) + SQLite**,
tanpa framework frontend dan tanpa API eksternal. Seluruh kode berada dalam satu
folder project dan siap dijalankan secara lokal.

## Cara Menjalankan

```bash
cd LaptopBekasApp
pip install -r requirements.txt
python app.py
```

Buka browser ke: **http://127.0.0.1:5000**

## Shortcut / Launcher

### Windows
- Jalankan file [run_app.bat](run_app.bat) untuk membuka aplikasi dengan cepat.
- Atau buat shortcut dari file [run_app.bat](run_app.bat) ke desktop:
  1. Klik kanan file [run_app.bat](run_app.bat).
  2. Pilih **Create shortcut**.
  3. Pindahkan shortcut ke desktop atau Start Menu.
  4. Jika ingin icon lebih rapi, klik kanan shortcut > **Properties** > **Change Icon**.

### VS Code
- Buka terminal di folder project lalu jalankan:
  ```bash
  python app.py
  ```
- Atau gunakan tombol **Run Python File** pada [app.py](app.py).

Database SQLite (`database.db`) akan **otomatis dibuat** saat pertama kali
`app.py` dijalankan, lengkap dengan seluruh tabel dan akun default.

## Akun Default

| Peran | Username | Password | Keterangan |
|---|---|---|---|
| Admin | `admin` | `admin123` | Pengguna operasional harian (bisa dibatasi hak aksesnya) |
| Root  | `root`  | `root123`  | Super admin tersembunyi, akses penuh ke semua halaman |

> **Penting:** Segera ganti password default melalui menu **Profil Saya**
> setelah login pertama kali, khususnya untuk akun `root`.

Akun **Root**:
- Tidak pernah muncul di menu **Pengguna** (Show User) — sengaja disembunyikan.
- Selalu memiliki akses ke seluruh halaman, tidak bisa dibatasi.
- Satu-satunya peran yang bisa membuka menu **Hak Akses** dan **Konfigurasi**.
- Tidak bisa dihapus atau diedit lewat menu Pengguna biasa; ganti nama/password
  root melalui menu **Profil Saya** saat login sebagai root.

## Struktur Folder

```
LaptopBekasApp/
│ app.py              # Entry point aplikasi, seluruh routing Flask
│ models.py           # Koneksi & skema database SQLite, helper hak akses/konfigurasi
│ reports.py          # Helper pembuatan PDF (nota & laporan) dan Excel
│ requirements.txt
│ README.md
│ database.db         # Dibuat otomatis saat pertama kali dijalankan
│
├── templates/         # Seluruh halaman HTML (Jinja2)
└── static/
    ├── css/style.css  # Tema biru-putih, responsive
    ├── js/main.js
    └── images/
```

## Fitur Utama

- **Login Admin** dengan password ter-hash (Werkzeug), logout, dan sesi login.
- **Dashboard** — kartu statistik (stok, terjual, modal, penjualan, pengeluaran,
  laba/rugi, saldo kas) beserta grafik penjualan/pengeluaran/cash flow per bulan
  (Chart.js).
- **Pembelian Laptop** — form lengkap (spesifikasi, biaya servis/upgrade/lain,
  total modal otomatis), CRUD, pencarian, cetak nota PDF. Setiap pembelian
  otomatis menjadi Master Laptop dengan status **Ready**.
- **Stok Laptop** — daftar laptop berstatus Ready beserta pencarian.
- **Penjualan** — pilih laptop dari stok Ready, laba dihitung otomatis
  (`Harga Jual - Total Modal`), status laptop berubah menjadi **Terjual**
  dan hilang dari daftar stok, cetak nota PDF.
- **Pengeluaran Kas** — kategori (Listrik, Internet, Transport, dll), CRUD.
- **Cash Flow** — arus kas otomatis dari pembelian, penjualan, dan pengeluaran,
  dengan saldo berjalan dan filter periode (harian/bulanan/tahunan/kustom).
- **Laporan lengkap**: Pembelian, Penjualan, Stok Ready, Riwayat Terjual,
  Pengeluaran, Cash Flow, dan Laba Rugi — semuanya bisa difilter per periode
  dan diekspor ke **PDF**, **Excel**, atau **Print** langsung dari browser.
- **Pencarian** tersedia di semua halaman data (merk, seri, processor, RAM,
  storage, serial number, nama pembeli/penjual, dsb).
- **Validasi**: harga tidak boleh minus, laptop yang sudah terjual tidak bisa
  dijual ulang atau dihapus dari data pembelian, nomor transaksi otomatis.

## Hak Akses & Konfigurasi (Fitur Tambahan)

- **Hak Akses Halaman** (`/hak-akses`, khusus Root): Root dapat mencentang/
  menghilangkan akses tiap pengguna admin ke masing-masing menu (Dashboard,
  Pembelian, Stok, Penjualan, Pengeluaran, Cash Flow, Laporan, Pengguna).
  Jika seorang admin tidak memiliki akses ke suatu halaman, ia akan diarahkan
  kembali ke Dashboard beserta pesan peringatan saat mencoba membukanya.
- **Konfigurasi Aplikasi** (`/konfigurasi`, khusus Root): mengubah nama
  aplikasi (brand di sidebar & judul tab), judul/tagline halaman login, serta
  warna tema utama dan warna sidebar — tersimpan di tabel `settings` dan
  langsung diterapkan ke seluruh halaman.
- **Profil Saya** (`/profil`, semua pengguna termasuk Root): mengubah nama
  dan password akun sendiri.

## Database SQLite

Tabel yang dibuat otomatis: `users`, `laptop`, `penjualan`, `pengeluaran`,
`cashflow`, `settings`, `page_access` — lengkap dengan relasi antar tabel
(`penjualan.laptop_id → laptop.id`, `page_access.user_id → users.id`).

## Catatan

- Aplikasi ini menggunakan Flask development server (`debug=True`) yang cocok
  untuk penggunaan lokal/demo. Untuk produksi, gunakan WSGI server seperti
  Gunicorn/Waitress dan matikan mode debug.
- `app.secret_key` di `app.py` sebaiknya diganti dengan nilai acak yang aman
  sebelum digunakan secara nyata.
