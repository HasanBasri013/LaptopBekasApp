"""
models.py
Modul koneksi database SQLite dan inisialisasi skema tabel
untuk aplikasi Sistem Jual Beli Laptop Bekas.
"""

import sqlite3
import os
import sys
from datetime import datetime
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
##DB_PATH = os.path.join(BASE_DIR, "database.db")

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(BASE_DIR, "database.db")

def get_db_connection():
    """Membuka koneksi baru ke database SQLite."""
    print("Menggunakan database:", DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Membuat seluruh tabel jika belum ada, dan membuat user admin default."""
    is_new = not os.path.exists(DB_PATH)
    conn = get_db_connection()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nama TEXT,
            role TEXT DEFAULT 'admin',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS laptop (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nomor_pembelian TEXT UNIQUE NOT NULL,
            tanggal TEXT NOT NULL,
            merk TEXT,
            seri TEXT,
            processor TEXT,
            ram TEXT,
            storage TEXT,
            vga TEXT,
            warna TEXT,
            kondisi TEXT,
            kelengkapan TEXT,
            charger TEXT,
            tas TEXT,
            garansi TEXT,
            imei TEXT,
            harga_beli REAL DEFAULT 0,
            biaya_servis REAL DEFAULT 0,
            biaya_upgrade REAL DEFAULT 0,
            biaya_lain REAL DEFAULT 0,
            total_modal REAL DEFAULT 0,
            supplier TEXT,
            no_hp TEXT,
            catatan TEXT,
            status TEXT DEFAULT 'Ready',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS penjualan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nomor_penjualan TEXT UNIQUE NOT NULL,
            tanggal TEXT NOT NULL,
            laptop_id INTEGER NOT NULL,
            pembeli TEXT,
            no_hp TEXT,
            harga_jual REAL DEFAULT 0,
            metode_pembayaran TEXT,
            catatan TEXT,
            laba REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (laptop_id) REFERENCES laptop (id)
        );

        CREATE TABLE IF NOT EXISTS pengeluaran (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nomor TEXT UNIQUE NOT NULL,
            tanggal TEXT NOT NULL,
            kategori TEXT,
            keterangan TEXT,
            nominal REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS cashflow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tanggal TEXT NOT NULL,
            keterangan TEXT,
            tipe TEXT NOT NULL,
            nominal REAL DEFAULT 0,
            ref_type TEXT,
            ref_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS page_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            page_key TEXT NOT NULL,
            allowed INTEGER DEFAULT 1,
            UNIQUE(user_id, page_key),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        """
    )

    # --- Migrasi kolom baru (untuk database lama yang sudah ada) ---
    cur.execute("PRAGMA table_info(penjualan)")
    existing_cols = {row["name"] for row in cur.fetchall()}
    if "diskon" not in existing_cols:
        cur.execute("ALTER TABLE penjualan ADD COLUMN diskon REAL DEFAULT 0")
    if "pajak" not in existing_cols:
        cur.execute("ALTER TABLE penjualan ADD COLUMN pajak REAL DEFAULT 0")
    if "grand_total" not in existing_cols:
        cur.execute("ALTER TABLE penjualan ADD COLUMN grand_total REAL DEFAULT 0")
        cur.execute("UPDATE penjualan SET grand_total = harga_jual WHERE grand_total IS NULL OR grand_total = 0")

    # Buat user admin default jika tabel users masih kosong.
    # Diberi role 'administrator' agar memiliki akses konfigurasi operasional penuh
    # (setara Root, kecuali fitur khusus Root seperti manajemen akun Root).
    cur.execute("SELECT COUNT(*) AS total FROM users")
    if cur.fetchone()["total"] == 0:
        cur.execute(
            "INSERT INTO users (username, password_hash, nama, role) VALUES (?, ?, ?, ?)",
            ("admin", generate_password_hash("admin123"), "Administrator", "administrator"),
        )

    # Buat user root (super admin tersembunyi) jika belum ada.
    # Root memiliki akses penuh ke seluruh halaman dan tidak muncul di menu Pengguna.
    cur.execute("SELECT COUNT(*) AS total FROM users WHERE role = 'root'")
    if cur.fetchone()["total"] == 0:
        cur.execute(
            "INSERT INTO users (username, password_hash, nama, role) VALUES (?, ?, ?, ?)",
            ("root", generate_password_hash("root123"), "Root Administrator", "root"),
        )

    # Nilai konfigurasi default (judul & warna dapat diubah lewat menu Konfigurasi)
    default_settings = {
        "app_title": "LaptopBekasApp",
        "company_name": "LaptopBekasApp",
        "company_address": "Jl. Jend. Sudirman No. 123, Jakarta",
        "company_contact": "0812-3456-7890",
        "login_title": "Sistem Jual Beli Laptop Bekas",
        "login_icon": "bi bi-laptop",
        "login_logo": "",
        "color_primary": "#0d6efd",
        "color_sidebar": "#0b3d91",
    }
    for k, v in default_settings.items():
        cur.execute("SELECT 1 FROM settings WHERE key = ?", (k,))
        if not cur.fetchone():
            cur.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()
    conn.close()
    return is_new


def generate_nomor(prefix, table, column):
    """
    Membuat nomor transaksi otomatis dengan format PREFIX-YYYYMMDD-XXX
    berdasarkan jumlah transaksi pada tanggal yang sama.
    """
    today = datetime.now().strftime("%Y%m%d")
    conn = get_db_connection()
    cur = conn.cursor()
    like_pattern = f"{prefix}-{today}-%"
    cur.execute(
        f"SELECT COUNT(*) AS total FROM {table} WHERE {column} LIKE ?", (like_pattern,)
    )
    total = cur.fetchone()["total"]
    conn.close()
    urutan = str(total + 1).zfill(3)
    return f"{prefix}-{today}-{urutan}"


# ---------------------------------------------------------------------------
# Konfigurasi Aplikasi (judul, warna) - dapat diubah oleh user root
# ---------------------------------------------------------------------------

def get_all_settings():
    """Mengambil seluruh baris settings sebagai dict {key: value}."""
    conn = get_db_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def update_settings(data: dict):
    """Menyimpan/memperbarui beberapa nilai settings sekaligus."""
    conn = get_db_connection()
    for k, v in data.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (k, v),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Hak Akses Halaman (page_access) - dikonfigurasi oleh user root
# ---------------------------------------------------------------------------

# Daftar halaman utama yang dapat diatur hak aksesnya.
PAGE_LIST = [
    ("dashboard", "Dashboard"),
    ("pembelian", "Pembelian Laptop"),
    ("stok", "Stok Laptop"),
    ("penjualan", "Penjualan"),
    ("pengeluaran", "Pengeluaran"),
    ("cashflow", "Cash Flow"),
    ("laporan", "Laporan"),
    ("pengguna", "Pengguna"),
]


# ---------------------------------------------------------------------------
# Role & Hierarki Pengguna
# ---------------------------------------------------------------------------

# Daftar seluruh role yang tersedia di aplikasi, urut dari tertinggi ke terendah.
ROLE_CHOICES = [
    ("root", "Root"),
    ("administrator", "Administrator"),
    ("admin", "Admin"),
    ("kasir", "Kasir"),
    ("gudang", "Gudang"),
]
ROLE_LABELS = dict(ROLE_CHOICES)

# Role yang diperlakukan setara "super user" (bypass hak akses per halaman,
# dan boleh mengakses menu Konfigurasi/Hak Akses). Hanya 'root' yang boleh
# mengelola akun ber-role root.
SUPERUSER_ROLES = ("root", "administrator")


def allowed_roles_for(current_role):
    """
    Mengembalikan daftar pilihan role yang boleh dipilih pada dropdown
    Tambah/Edit Pengguna, tergantung role user yang sedang login.
    Root -> semua role. Selain root -> semua role kecuali Root.
    """
    if current_role == "root":
        return ROLE_CHOICES
    return [(k, v) for k, v in ROLE_CHOICES if k != "root"]


def has_page_access(user_id, role, page_key):
    """
    Root & Administrator selalu memiliki akses penuh ke semua halaman.
    Untuk role lain (admin, kasir, gudang, dst), default diizinkan kecuali
    ada baris page_access dengan allowed = 0 (ditolak secara eksplisit).
    """
    if role in SUPERUSER_ROLES:
        return True
    conn = get_db_connection()
    row = conn.execute(
        "SELECT allowed FROM page_access WHERE user_id = ? AND page_key = ?",
        (user_id, page_key),
    ).fetchone()
    conn.close()
    if row is None:
        return True
    return bool(row["allowed"])


def get_access_matrix():
    """
    Mengembalikan daftar user non-superuser (bukan Root/Administrator) beserta
    status akses tiap halaman, untuk ditampilkan pada halaman Hak Akses.
    Root & Administrator tidak perlu diatur karena selalu memiliki akses penuh.
    """
    conn = get_db_connection()
    users = conn.execute(
        "SELECT id, username, nama, role FROM users WHERE role NOT IN ('root','administrator') ORDER BY id"
    ).fetchall()
    access_rows = conn.execute("SELECT user_id, page_key, allowed FROM page_access").fetchall()
    conn.close()

    access_map = {(r["user_id"], r["page_key"]): bool(r["allowed"]) for r in access_rows}
    matrix = []
    for u in users:
        pages = {}
        for key, label in PAGE_LIST:
            pages[key] = access_map.get((u["id"], key), True)
        matrix.append({
            "id": u["id"], "username": u["username"], "nama": u["nama"],
            "role": u["role"], "role_label": ROLE_LABELS.get(u["role"], u["role"]),
            "pages": pages,
        })
    return matrix


def save_access_matrix(form):
    """
    Menyimpan hak akses berdasarkan data form (checkbox) halaman Hak Akses.
    Nama field checkbox: access_{user_id}_{page_key}
    """
    conn = get_db_connection()
    users = conn.execute("SELECT id FROM users WHERE role NOT IN ('root','administrator')").fetchall()
    for u in users:
        for key, label in PAGE_LIST:
            field = f"access_{u['id']}_{key}"
            allowed = 1 if form.get(field) else 0
            conn.execute(
                "INSERT INTO page_access (user_id, page_key, allowed) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, page_key) DO UPDATE SET allowed = excluded.allowed",
                (u["id"], key, allowed),
            )
    conn.commit()
    conn.close()