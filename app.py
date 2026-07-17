"""
app.py
Aplikasi Sistem Jual Beli Laptop Bekas
Flask + SQLite (tanpa ORM eksternal, tanpa API eksternal)
Jalankan dengan: python app.py
Akses di: http://127.0.0.1:5000
"""

import os
from datetime import datetime, timedelta
from functools import wraps
import tempfile
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_file, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from models import (
    get_db_connection, init_db, generate_nomor,
    get_all_settings, update_settings,
    has_page_access, get_access_matrix, save_access_matrix, PAGE_LIST,
    allowed_roles_for,
)
import reports
from reportlab.platypus import Macro

app = Flask(__name__)
app.secret_key = "laptopbekasapp-secret-key-ubah-ini-di-produksi"

# ---------------------------------------------------------------------------
# Helper & Decorator
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Silakan login terlebih dahulu.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def page_required(page_key):
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                flash("Silakan login terlebih dahulu.", "warning")
                return redirect(url_for("login"))
            if not has_page_access(session["user_id"], session.get("role"), page_key):
                flash("Anda tidak memiliki hak akses ke halaman ini. Hubungi administrator.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return wrapper


def root_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Silakan login terlebih dahulu.", "warning")
            return redirect(url_for("login"))
        if session.get("role") not in ("root", "administrator"):
            flash("Halaman ini hanya dapat diakses oleh Root atau Administrator.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def can_access_page(page_key: str) -> bool:
    if "user_id" not in session:
        return False
    if page_key in {"konfigurasi", "hak_akses"}:
        return session.get("role") in ("root", "administrator")
    return has_page_access(session["user_id"], session.get("role"), page_key)


def to_float(value, default=0.0):
    try:
        value = str(value).replace(".", "").replace(",", ".").strip()
        v = float(value or 0)
        return v if v >= 0 else default
    except (TypeError, ValueError):
        return default


def hitung_saldo_awal(start_date):
    if not start_date:
        return 0
    conn = get_db_connection()
    masuk = conn.execute(
        """
        SELECT COALESCE(SUM(nominal),0) t
        FROM cashflow
        WHERE tipe='masuk'
        AND tanggal < ?
        """,
        (start_date,),
    ).fetchone()["t"]
    keluar = conn.execute(
        """
        SELECT COALESCE(SUM(nominal),0) t
        FROM cashflow
        WHERE tipe='keluar'
        AND tanggal < ?
        """,
        (start_date,),
    ).fetchone()["t"]
    conn.close()
    return masuk - keluar


def get_period_range():
    def _is_true(v):
        return str(v).lower() in ("1", "true", "on", "yes")
    today = datetime.now().date()
    first_of_month = today.replace(day=1)
    next_month = (first_of_month + timedelta(days=32)).replace(day=1)
    last_of_month = next_month - timedelta(days=1)
    has_period_args = any(k in request.args for k in ("use_start", "use_end", "start_date", "end_date"))
    use_start = _is_true(request.args.get("use_start", ""))
    use_end = _is_true(request.args.get("use_end", ""))
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    if not has_period_args:
        use_start = True
        use_end = True
        start_date = first_of_month.strftime("%Y-%m-%d")
        end_date = last_of_month.strftime("%Y-%m-%d")
    else:
        if use_start and not start_date:
            start_date = first_of_month.strftime("%Y-%m-%d")
        if use_end and not end_date:
            end_date = last_of_month.strftime("%Y-%m-%d")
        if not use_start:
            start_date = ""
        if not use_end:
            end_date = ""
    return use_start, use_end, start_date, end_date


@app.context_processor
def inject_globals():
    return {
        "rp": reports.rp,
        "current_year": datetime.now().year,
        "now_date": datetime.now().strftime("%Y-%m-%d"),
        "app_settings": get_all_settings(),
        "can_access_page": can_access_page,
    }


@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        f = request.form
        username = (f.get("username") or "").strip()
        password = f.get("password") or ""
        conn = get_db_connection()
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if not row:
            flash("Username tidak ditemukan.", "danger")
            return redirect(url_for("login"))
        if not check_password_hash(row["password_hash"], password):
            flash("Password salah.", "danger")
            return redirect(url_for("login"))
        session["user_id"] = row["id"]
        session["username"] = row["username"]
        role = None
        try:
            role = row["role"]
        except Exception:
            role = None
        session["role"] = role or "admin"
        flash("Login berhasil.", "success")
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Anda telah logout.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@page_required("dashboard")
def dashboard():
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()

    total_ready = conn.execute("SELECT COUNT(*) c FROM laptop WHERE status='Ready'").fetchone()["c"]

    q = "SELECT COUNT(*) c FROM penjualan WHERE 1=1"
    params = []
    if start_date:
        q += " AND tanggal >= ?"; params.append(start_date)
    if end_date:
        q += " AND tanggal <= ?"; params.append(end_date)
    total_terjual = conn.execute(q, params).fetchone()["c"]

    nilai_stok = conn.execute("SELECT COALESCE(SUM(total_modal),0) total FROM laptop WHERE status='Ready'").fetchone()["total"]

    q_in = "SELECT COALESCE(SUM(nominal),0) total FROM cashflow WHERE tipe='masuk' AND IFNULL(ref_type,'') <> 'saldo_awal_kas'"
    q_out = "SELECT COALESCE(SUM(nominal),0) total FROM cashflow WHERE tipe='keluar'"
    params_in = []
    params_out = []
    if start_date:
        q_in += " AND tanggal >= ?"; params_in.append(start_date)
        q_out += " AND tanggal >= ?"; params_out.append(start_date)
    if end_date:
        q_in += " AND tanggal <= ?"; params_in.append(end_date)
        q_out += " AND tanggal <= ?"; params_out.append(end_date)
    total_kas_masuk = conn.execute(q_in, params_in).fetchone()["total"]
    total_kas_keluar = conn.execute(q_out, params_out).fetchone()["total"]

    q = "SELECT COALESCE(SUM(harga_jual),0) total FROM penjualan WHERE 1=1"
    qparams = []
    if start_date:
        q += " AND tanggal >= ?"; qparams.append(start_date)
    if end_date:
        q += " AND tanggal <= ?"; qparams.append(end_date)
    total_penjualan = conn.execute(q, qparams).fetchone()["total"]

    q = "SELECT COALESCE(SUM(laba),0) total FROM penjualan WHERE 1=1"
    qparams = []
    if start_date:
        q += " AND tanggal >= ?"; qparams.append(start_date)
    if end_date:
        q += " AND tanggal <= ?"; qparams.append(end_date)
    laba_kotor = conn.execute(q, qparams).fetchone()["total"]

    q = "SELECT COALESCE(SUM(nominal),0) total FROM pengeluaran WHERE tipe='keluar'"
    qparams = []
    if start_date:
        q += " AND tanggal >= ?"; qparams.append(start_date)
    if end_date:
        q += " AND tanggal <= ?"; qparams.append(end_date)
    biaya_operasional = conn.execute(q, qparams).fetchone()["total"]

    laba_bersih = laba_kotor - biaya_operasional
    laba_rugi = laba_bersih
    margin_laba = (laba_bersih / total_penjualan * 100) if total_penjualan > 0 else 0

    saldo_awal = hitung_saldo_awal(start_date)
    saldo_kas = saldo_awal + total_kas_masuk - total_kas_keluar
    total_modal = nilai_stok + saldo_kas

    bulan_labels = []
    penjualan_per_bulan = []
    pengeluaran_per_bulan = []
    cashflow_masuk_per_bulan = []
    cashflow_keluar_per_bulan = []
    today = datetime.now().date()
    for i in range(5, -1, -1):
        y = today.year
        m = today.month - i
        while m <= 0:
            m += 12; y -= 1
        label = f"{m:02d}-{y}"
        ym = f"{y}-{m:02d}"
        bulan_labels.append(label)
        penjualan_per_bulan.append(conn.execute("SELECT COALESCE(SUM(harga_jual),0) FROM penjualan WHERE strftime('%Y-%m',tanggal)=?", (ym,)).fetchone()[0])
        pengeluaran_per_bulan.append(conn.execute("SELECT COALESCE(SUM(nominal),0) FROM pengeluaran WHERE strftime('%Y-%m',tanggal)=?", (ym,)).fetchone()[0])
        cashflow_masuk_per_bulan.append(conn.execute("SELECT COALESCE(SUM(nominal),0) FROM cashflow WHERE tipe='masuk' AND strftime('%Y-%m',tanggal)=?", (ym,)).fetchone()[0])
        cashflow_keluar_per_bulan.append(conn.execute("SELECT COALESCE(SUM(nominal),0) FROM cashflow WHERE tipe='keluar' AND strftime('%Y-%m',tanggal)=?", (ym,)).fetchone()[0])

    conn.close()

    return render_template("dashboard.html",
        total_ready=total_ready,
        total_terjual=total_terjual,
        nilai_stok=nilai_stok,
        total_modal=total_modal,
        total_penjualan=total_penjualan,
        laba_kotor=laba_kotor,
        laba_bersih=laba_bersih,
        laba_rugi=laba_rugi,
        biaya_operasional=biaya_operasional,
        margin_laba=margin_laba,
        total_kas_masuk=total_kas_masuk,
        total_kas_keluar=total_kas_keluar,
        saldo_kas=saldo_kas,
        bulan_labels=bulan_labels,
        penjualan_per_bulan=penjualan_per_bulan,
        pengeluaran_per_bulan=pengeluaran_per_bulan,
        cashflow_masuk_per_bulan=cashflow_masuk_per_bulan,
        cashflow_keluar_per_bulan=cashflow_keluar_per_bulan,
        use_start=use_start,
        use_end=use_end,
        start_date=start_date,
        end_date=end_date,
        saldo_awal=saldo_awal,
        saldo_akhir=saldo_kas,
        total_masuk=total_kas_masuk,
        total_keluar=total_kas_keluar,
    )

# ---------------------------------------------------------------------------
    q_sold = "SELECT COUNT(*) c FROM penjualan WHERE 1=1"
    params_sold = []
    if start_date:
        q_sold += " AND tanggal >= ?"; params_sold.append(start_date)
    if end_date:
        q_sold += " AND tanggal <= ?"; params_sold.append(end_date)
    total_terjual = conn.execute(q_sold, params_sold).fetchone()["c"]


    # Nilai modal semua stok ready
    nilai_stok = conn.execute("""
        SELECT COALESCE(SUM(total_modal),0) total
        FROM laptop
        WHERE status='Ready'
    """).fetchone()["total"]

    # =========================
    # CASHFLOW
    # =========================

    # saldo awal (tidak dibatasi periode)
    saldo_awal = conn.execute("SELECT COALESCE(SUM(nominal),0) total FROM cashflow WHERE ref_type='saldo_awal_kas'").fetchone()["total"]

    # kas masuk/keluar pada periode
    q_in = "SELECT COALESCE(SUM(nominal),0) total FROM cashflow WHERE tipe='masuk' AND IFNULL(ref_type,'') <> 'saldo_awal_kas'"
    q_out = "SELECT COALESCE(SUM(nominal),0) total FROM cashflow WHERE tipe='keluar'"
    params_in = []
    params_out = []
    if start_date:
        q_in += " AND tanggal >= ?"; params_in.append(start_date)
        q_out += " AND tanggal >= ?"; params_out.append(start_date)
    if end_date:
        q_in += " AND tanggal <= ?"; params_in.append(end_date)
        q_out += " AND tanggal <= ?"; params_out.append(end_date)
    total_kas_masuk = conn.execute(q_in, params_in).fetchone()["total"]
    total_kas_keluar = conn.execute(q_out, params_out).fetchone()["total"]



    # =========================
    # PENJUALAN (hanya pada periode yang dipilih)
    # =========================
    q = "SELECT COALESCE(SUM(harga_jual),0) total FROM penjualan WHERE 1=1"
    qparams = []
    if start_date:
        q += " AND tanggal >= ?"; qparams.append(start_date)
    if end_date:
        q += " AND tanggal <= ?"; qparams.append(end_date)
    total_penjualan = conn.execute(q, qparams).fetchone()["total"]

    # laba kotor dari transaksi pada periode
    q = "SELECT COALESCE(SUM(laba),0) total FROM penjualan WHERE 1=1"
    qparams = []
    if start_date:
        q += " AND tanggal >= ?"; qparams.append(start_date)
    if end_date:
        q += " AND tanggal <= ?"; qparams.append(end_date)
    laba_kotor = conn.execute(q, qparams).fetchone()["total"]


    # =========================
    # BIAYA OPERASIONAL (periode)
    # =========================
    q = "SELECT COALESCE(SUM(nominal),0) total FROM pengeluaran WHERE tipe='keluar'"
    qparams = []
    if start_date:
        q += " AND tanggal >= ?"; qparams.append(start_date)
    if end_date:
        q += " AND tanggal <= ?"; qparams.append(end_date)
    biaya_operasional = conn.execute(q, qparams).fetchone()["total"]



    # laba bersih
    laba_bersih = laba_kotor - biaya_operasional



    # margin
    margin_laba = 0

    if total_penjualan > 0:
        margin_laba = (laba_bersih / total_penjualan) * 100



    # =========================
    # CASHFLOW
    # =========================

    saldo_awal = conn.execute("""
        SELECT COALESCE(SUM(nominal),0) total
        FROM cashflow
        WHERE ref_type='saldo_awal_kas'
    """).fetchone()["total"]



    total_kas_masuk = conn.execute("""
        SELECT COALESCE(SUM(nominal),0) total
        FROM cashflow
        WHERE tipe='masuk'
        AND IFNULL(ref_type,'') <> 'saldo_awal_kas'
    """).fetchone()["total"]



    total_kas_keluar = conn.execute("""
        SELECT COALESCE(SUM(nominal),0) total
        FROM cashflow
        WHERE tipe='keluar'
    """).fetchone()["total"]



    saldo_kas = saldo_awal + total_kas_masuk - total_kas_keluar



    # Modal berjalan = nilai barang + uang usaha
    total_modal = nilai_stok + saldo_kas



    # =========================
    # GRAFIK 6 BULAN
    # =========================

    bulan_labels = []
    penjualan_per_bulan = []
    pengeluaran_per_bulan = []
    cashflow_masuk_per_bulan = []
    cashflow_keluar_per_bulan = []


    today = datetime.now().date()

    for i in range(5, -1, -1):

        year = today.year
        month = today.month - i

        while month <= 0:
            month += 12
            year -= 1


        label = f"{month:02d}-{year}"
        ym = f"{year}-{month:02d}"

        bulan_labels.append(label)


        penjualan_per_bulan.append(
            conn.execute("""
                SELECT COALESCE(SUM(harga_jual),0)
                FROM penjualan
                WHERE strftime('%Y-%m',tanggal)=?
            """,(ym,)).fetchone()[0]
        )


        pengeluaran_per_bulan.append(
            conn.execute("""
                SELECT COALESCE(SUM(nominal),0)
                FROM pengeluaran
                WHERE strftime('%Y-%m',tanggal)=?
            """,(ym,)).fetchone()[0]
        )


        cashflow_masuk_per_bulan.append(
            conn.execute("""
                SELECT COALESCE(SUM(nominal),0)
                FROM cashflow
                WHERE tipe='masuk'
                AND strftime('%Y-%m',tanggal)=?
            """,(ym,)).fetchone()[0]
        )


        cashflow_keluar_per_bulan.append(
            conn.execute("""
                SELECT COALESCE(SUM(nominal),0)
                FROM cashflow
                WHERE tipe='keluar'
                AND strftime('%Y-%m',tanggal)=?
            """,(ym,)).fetchone()[0]
        )


    conn.close()


    return render_template(
        "dashboard.html",

        total_ready=total_ready,
        total_terjual=total_terjual,

        nilai_stok=nilai_stok,
        total_modal=total_modal,

        total_penjualan=total_penjualan,

        laba_kotor=laba_kotor,
        laba_bersih=laba_bersih,
        laba_rugi=laba_bersih,

        biaya_operasional=biaya_operasional,
        margin_laba=margin_laba,

        total_kas_masuk=total_kas_masuk,
        total_kas_keluar=total_kas_keluar,
        saldo_kas=saldo_kas,

        bulan_labels=bulan_labels,
        penjualan_per_bulan=penjualan_per_bulan,
        pengeluaran_per_bulan=pengeluaran_per_bulan,
        cashflow_masuk_per_bulan=cashflow_masuk_per_bulan,
        cashflow_keluar_per_bulan=cashflow_keluar_per_bulan,
        use_start=use_start,
        use_end=use_end,
        start_date=start_date,
        end_date=end_date,
    )

# ---------------------------------------------------------------------------
# PEMBELIAN LAPTOP (juga otomatis membuat Master Laptop)
# ---------------------------------------------------------------------------

@app.route("/pembelian")
@page_required("pembelian")
def pembelian_list():
    q = request.args.get("q", "").strip()
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()
    base = "SELECT * FROM laptop WHERE 1=1"
    params = []
    if q:
        like = f"%{q}%"
        base += " AND (merk LIKE ? OR seri LIKE ? OR processor LIKE ? OR ram LIKE ? OR storage LIKE ? OR imei LIKE ? OR supplier LIKE ? OR nomor_pembelian LIKE ?)"
        params.extend([like] * 8)
    if start_date:
        base += " AND tanggal >= ?"
        params.append(start_date)
    if end_date:
        base += " AND tanggal <= ?"
        params.append(end_date)
    base += " ORDER BY tanggal DESC"
    rows = conn.execute(base, params).fetchall()
    conn.close()
    return render_template("pembelian_list.html", rows=rows, q=q, use_start=use_start, use_end=use_end, start_date=start_date, end_date=end_date)
@app.route("/pembelian/tambah", methods=["GET", "POST"])
@page_required("pembelian")
def pembelian_tambah():
    if request.method == "POST":
        f = request.form
        harga_beli = to_float(f.get("harga_beli"))
        biaya_servis = to_float(f.get("biaya_servis"))
        biaya_upgrade = to_float(f.get("biaya_upgrade"))
        biaya_lain = to_float(f.get("biaya_lain"))
        modal_laptop = harga_beli + biaya_servis + biaya_upgrade + biaya_lain
        tanggal = f.get("tanggal") or datetime.now().strftime("%Y-%m-%d")

        conn = get_db_connection()
        nomor = generate_nomor("PB", "laptop", "nomor_pembelian")
        cur = conn.execute(
            """INSERT INTO laptop
               (nomor_pembelian, tanggal, merk, seri, processor, ram, storage, vga, warna,
                kondisi, kelengkapan, charger, tas, garansi, imei, harga_beli, biaya_servis,
                biaya_upgrade, biaya_lain, total_modal, supplier, no_hp, catatan, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'Ready')""",
            (nomor, tanggal, f.get("merk"), f.get("seri"), f.get("processor"), f.get("ram"),
             f.get("storage"), f.get("vga"), f.get("warna"), f.get("kondisi"),
             f.get("kelengkapan"), f.get("charger"), f.get("tas"), f.get("garansi"),
             f.get("imei"), harga_beli, biaya_servis, biaya_upgrade, biaya_lain,
             modal_laptop, f.get("supplier"), f.get("no_hp"), f.get("catatan")),
        )
        laptop_id = cur.lastrowid
        conn.execute(
            """INSERT INTO cashflow (tanggal, keterangan, tipe, nominal, ref_type, ref_id)
               VALUES (?,?,?,?,?,?)""",
            (tanggal, f"Pembelian Laptop {f.get('merk')} {f.get('seri')} ({nomor})",
             "keluar", modal_laptop, "pembelian", laptop_id),
        )
        conn.commit()
        conn.close()
        flash(f"Pembelian berhasil disimpan dengan nomor {nomor}.", "success")
        return redirect(url_for("pembelian_list"))

    nomor_preview = generate_nomor("PB", "laptop", "nomor_pembelian")
    return render_template("pembelian_form.html", row=None, nomor_preview=nomor_preview)


@app.route("/pembelian/edit/<int:id>", methods=["GET", "POST"])
@page_required("pembelian")
def pembelian_edit(id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM laptop WHERE id = ?", (id,)).fetchone()
    if not row:
        conn.close()
        flash("Data laptop tidak ditemukan.", "danger")
        return redirect(url_for("pembelian_list"))

    if request.method == "POST":
        f = request.form
        harga_beli = to_float(f.get("harga_beli"))
        biaya_servis = to_float(f.get("biaya_servis"))
        biaya_upgrade = to_float(f.get("biaya_upgrade"))
        biaya_lain = to_float(f.get("biaya_lain"))
        modal_laptop  = harga_beli + biaya_servis + biaya_upgrade + biaya_lain
        tanggal = f.get("tanggal") or row["tanggal"]

        conn.execute(
            """UPDATE laptop SET tanggal=?, merk=?, seri=?, processor=?, ram=?, storage=?,
               vga=?, warna=?, kondisi=?, kelengkapan=?, charger=?, tas=?, garansi=?, imei=?,
               harga_beli=?, biaya_servis=?, biaya_upgrade=?, biaya_lain=?, total_modal=?,
               supplier=?, no_hp=?, catatan=? WHERE id=?""",
            (tanggal, f.get("merk"), f.get("seri"), f.get("processor"), f.get("ram"),
             f.get("storage"), f.get("vga"), f.get("warna"), f.get("kondisi"),
             f.get("kelengkapan"), f.get("charger"), f.get("tas"), f.get("garansi"),
             f.get("imei"), harga_beli, biaya_servis, biaya_upgrade, biaya_lain,
             modal_laptop, f.get("supplier"), f.get("no_hp"), f.get("catatan"), id),
        )
        conn.execute(
            """UPDATE cashflow SET tanggal=?, keterangan=?, nominal=?
               WHERE ref_type='pembelian' AND ref_id=?""",
            (tanggal, f"Pembelian Laptop {f.get('merk')} {f.get('seri')} ({row['nomor_pembelian']})",
             modal_laptop, id),
        )
        conn.commit()
        conn.close()
        flash("Data pembelian berhasil diperbarui.", "success")
        return redirect(url_for("pembelian_list"))

    conn.close()
    return render_template("pembelian_form.html", row=row, nomor_preview=row["nomor_pembelian"])


@app.route("/pembelian/hapus/<int:id>", methods=["POST"])
@page_required("pembelian")
def pembelian_hapus(id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM laptop WHERE id = ?", (id,)).fetchone()
    if not row:
        flash("Data tidak ditemukan.", "danger")
    elif row["status"] == "Terjual":
        flash("Laptop sudah terjual, tidak dapat dihapus dari data pembelian.", "danger")
    else:
        conn.execute("DELETE FROM cashflow WHERE ref_type='pembelian' AND ref_id=?", (id,))
        conn.execute("DELETE FROM laptop WHERE id=?", (id,))
        conn.commit()
        flash("Data pembelian berhasil dihapus.", "success")
    conn.close()
    return redirect(url_for("pembelian_list"))


@app.route("/pembelian/cetak/<int:id>")
@page_required("pembelian")
def pembelian_cetak(id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM laptop WHERE id = ?", (id,)).fetchone()
    conn.close()
    if not row:
        flash("Data tidak ditemukan.", "danger")
        return redirect(url_for("pembelian_list"))
    buf = reports.buat_nota_pembelian_pdf(row)
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                      download_name=f"Nota_{row['nomor_pembelian']}.pdf")


# ---------------------------------------------------------------------------
# STOK LAPTOP (Ready)
# ---------------------------------------------------------------------------

@app.route("/stok")
@page_required("stok")
def stok_list():
    q = request.args.get("q", "").strip()
    conn = get_db_connection()
    base = "SELECT * FROM laptop WHERE status='Ready'"
    params = []
    if q:
        like = f"%{q}%"
        base += """ AND (merk LIKE ? OR seri LIKE ? OR processor LIKE ? OR ram LIKE ?
                   OR storage LIKE ? OR imei LIKE ?)"""
        params = [like, like, like, like, like, like]
    base += " ORDER BY id DESC"
    rows = conn.execute(base, params).fetchall()
    conn.close()
    return render_template("stok_list.html", rows=rows, q=q)


# ---------------------------------------------------------------------------
# PENJUALAN
# ---------------------------------------------------------------------------

@app.route("/penjualan")
@page_required("penjualan")
def penjualan_list():
    q = request.args.get("q", "").strip()
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()
    base = """SELECT p.*, l.merk, l.seri, l.total_modal, l.nomor_pembelian
              FROM penjualan p JOIN laptop l ON p.laptop_id = l.id WHERE 1=1"""
    params = []
    if q:
        like = f"%{q}%"
        base += " AND (p.pembeli LIKE ? OR l.merk LIKE ? OR l.seri LIKE ? OR p.nomor_penjualan LIKE ? OR l.nomor_pembelian LIKE ? OR l.imei LIKE ?)"
        params.extend([like, like, like, like, like, like])
    if start_date:
        base += " AND p.tanggal >= ?"
        params.append(start_date)
    if end_date:
        base += " AND p.tanggal <= ?"
        params.append(end_date)
    base += " ORDER BY p.tanggal DESC"
    rows = conn.execute(base, params).fetchall()
    conn.close()
    return render_template("penjualan_list.html", rows=rows, q=q, use_start=use_start, use_end=use_end, start_date=start_date, end_date=end_date)


@app.route("/penjualan/tambah", methods=["GET", "POST"])
@page_required("penjualan")
def penjualan_tambah():
    conn = get_db_connection()
    if request.method == "POST":
        f = request.form
        laptop_id = f.get("laptop_id")
        laptop = conn.execute("SELECT * FROM laptop WHERE id=?", (laptop_id,)).fetchone()

        if not laptop:
            flash("Laptop tidak ditemukan.", "danger")
        elif laptop["status"] == "Terjual":
            flash("Laptop ini sudah terjual dan tidak dapat dijual kembali.", "danger")
        else:
            harga_jual = to_float(f.get("harga_jual"))
            tanggal = f.get("tanggal") or datetime.now().strftime("%Y-%m-%d")
            laba = harga_jual - laptop["total_modal"]
            nomor = generate_nomor("JL", "penjualan", "nomor_penjualan")

            cur = conn.execute(
                """INSERT INTO penjualan
                   (nomor_penjualan, tanggal, laptop_id, pembeli, no_hp, harga_jual,
                    metode_pembayaran, catatan, laba)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (nomor, tanggal, laptop_id, f.get("pembeli"), f.get("no_hp"), harga_jual,
                 f.get("metode_pembayaran"), f.get("catatan"), laba),
            )
            penjualan_id = cur.lastrowid
            conn.execute("UPDATE laptop SET status='Terjual' WHERE id=?", (laptop_id,))
            conn.execute(
                """INSERT INTO cashflow (tanggal, keterangan, tipe, nominal, ref_type, ref_id)
                   VALUES (?,?,?,?,?,?)""",
                (tanggal, f"Penjualan Laptop {laptop['merk']} {laptop['seri']} ({nomor})",
                 "masuk", harga_jual, "penjualan", penjualan_id),
            )
            conn.commit()
            conn.close()
            flash(f"Penjualan berhasil disimpan dengan nomor {nomor}.", "success")
            return redirect(url_for("penjualan_list"))

    laptop_ready = conn.execute("SELECT * FROM laptop WHERE status='Ready' ORDER BY merk").fetchall()
    conn.close()
    nomor_preview = generate_nomor("JL", "penjualan", "nomor_penjualan")
    return render_template("penjualan_form.html", row=None, laptop_ready=laptop_ready,
                            nomor_preview=nomor_preview, laptop_terpilih=None)


@app.route("/penjualan/edit/<int:id>", methods=["GET", "POST"])
@page_required("penjualan")
def penjualan_edit(id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM penjualan WHERE id=?", (id,)).fetchone()
    if not row:
        conn.close()
        flash("Data penjualan tidak ditemukan.", "danger")
        return redirect(url_for("penjualan_list"))
    laptop = conn.execute("SELECT * FROM laptop WHERE id=?", (row["laptop_id"],)).fetchone()

    if request.method == "POST":
        f = request.form
        harga_jual = to_float(f.get("harga_jual"))
        tanggal = f.get("tanggal") or row["tanggal"]
        laba = harga_jual - laptop["total_modal"]

        conn.execute(
            """UPDATE penjualan SET tanggal=?, pembeli=?, no_hp=?, harga_jual=?,
               metode_pembayaran=?, catatan=?, laba=? WHERE id=?""",
            (tanggal, f.get("pembeli"), f.get("no_hp"), harga_jual,
             f.get("metode_pembayaran"), f.get("catatan"), laba, id),
        )
        conn.execute(
            """UPDATE cashflow SET tanggal=?, nominal=? WHERE ref_type='penjualan' AND ref_id=?""",
            (tanggal, harga_jual, id),
        )
        conn.commit()
        conn.close()
        flash("Data penjualan berhasil diperbarui.", "success")
        return redirect(url_for("penjualan_list"))

    conn.close()
    return render_template("penjualan_form.html", row=row, laptop_ready=[laptop],
                            nomor_preview=row["nomor_penjualan"], laptop_terpilih=laptop)


@app.route("/penjualan/hapus/<int:id>", methods=["POST"])
@page_required("penjualan")
def penjualan_hapus(id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM penjualan WHERE id=?", (id,)).fetchone()
    if row:
        conn.execute("UPDATE laptop SET status='Ready' WHERE id=?", (row["laptop_id"],))
        conn.execute("DELETE FROM cashflow WHERE ref_type='penjualan' AND ref_id=?", (id,))
        conn.execute("DELETE FROM penjualan WHERE id=?", (id,))
        conn.commit()
        flash("Data penjualan berhasil dihapus. Laptop dikembalikan ke status Ready.", "success")
    else:
        flash("Data tidak ditemukan.", "danger")
    conn.close()
    return redirect(url_for("penjualan_list"))


@app.route("/penjualan/cetak/<int:id>")
@page_required("penjualan")
def penjualan_cetak(id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM penjualan WHERE id=?", (id,)).fetchone()
    if not row:
        conn.close()
        flash("Data tidak ditemukan.", "danger")
        return redirect(url_for("penjualan_list"))
    laptop = conn.execute("SELECT * FROM laptop WHERE id=?", (row["laptop_id"],)).fetchone()
    conn.close()
    buf = reports.buat_nota_penjualan_pdf(row, laptop)
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                      download_name=f"Nota_{row['nomor_penjualan']}.pdf")


# ---------------------------------------------------------------------------
# PENGELUARAN
# ---------------------------------------------------------------------------

KATEGORI_PENGELUARAN = [
    "Listrik", "Internet", "Transport", "Makan", "Servis",
    "Sparepart", "Gaji", "Sewa", "Operasional", "Lainnya",
]


@app.route("/pengeluaran")
@page_required("pengeluaran")
def pengeluaran_list():
    q = request.args.get("q", "").strip()
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()
    base = "SELECT * FROM pengeluaran WHERE 1=1"
    params = []
    if q:
        like = f"%{q}%"
        base += " AND (kategori LIKE ? OR keterangan LIKE ? OR nomor LIKE ?)"
        params.extend([like, like, like])
    if start_date:
        base += " AND tanggal >= ?"
        params.append(start_date)
    if end_date:
        base += " AND tanggal <= ?"
        params.append(end_date)
    base += " ORDER BY tanggal DESC"
    rows = conn.execute(base, params).fetchall()
    conn.close()
    return render_template("pengeluaran_list.html", rows=rows, q=q, kategori_list=KATEGORI_PENGELUARAN, use_start=use_start, use_end=use_end, start_date=start_date, end_date=end_date)


@app.route("/pengeluaran/tambah", methods=["GET", "POST"])
@page_required("pengeluaran")
def pengeluaran_tambah():
    if request.method == "POST":
        f = request.form
        nominal = to_float(f.get("nominal"))
        tanggal = f.get("tanggal") or datetime.now().strftime("%Y-%m-%d")
        tipe = f.get("tipe", "keluar")
        if tipe not in ("masuk", "keluar"):
            flash("Jenis transaksi tidak valid.", "danger")
            return redirect(url_for("pengeluaran_tambah"))

        conn = get_db_connection()
        nomor = generate_nomor("EX", "pengeluaran", "nomor")
        cur = conn.execute(
            """
            INSERT INTO pengeluaran
            (nomor, tanggal, tipe, kategori, keterangan, nominal)
            VALUES (?,?,?,?,?,?)
            """,
            (
                nomor,
                tanggal,
                tipe,
                f.get("kategori"),
                f.get("keterangan"),
                nominal,
            ),
        )
        pid = cur.lastrowid
        conn.execute(
            """INSERT INTO cashflow (tanggal, keterangan, tipe, nominal, ref_type, ref_id)
               VALUES (?,?,?,?,?,?)""",
            (tanggal, f"{f.get('kategori')} - {f.get('keterangan') or nomor}", tipe, nominal,
             "pengeluaran", pid),
        )
        conn.commit()
        conn.close()
        flash(f"Pengeluaran berhasil disimpan dengan nomor {nomor}.", "success")
        return redirect(url_for("pengeluaran_list"))

    nomor_preview = generate_nomor("EX", "pengeluaran", "nomor")
    return render_template("pengeluaran_form.html", row=None, nomor_preview=nomor_preview,
                            kategori_list=KATEGORI_PENGELUARAN)


@app.route("/pengeluaran/edit/<int:id>", methods=["GET", "POST"])
@page_required("pengeluaran")
def pengeluaran_edit(id):
    conn = get_db_connection()
    row = conn.execute(
        """SELECT p.*, c.tipe FROM pengeluaran p
           LEFT JOIN cashflow c ON c.ref_type='pengeluaran' AND c.ref_id=p.id
           WHERE p.id=?""",
        (id,),
    ).fetchone()
    if not row:
        conn.close()
        flash("Data tidak ditemukan.", "danger")
        return redirect(url_for("pengeluaran_list"))

    if request.method == "POST":
        f = request.form
        nominal = to_float(f.get("nominal"))
        tanggal = f.get("tanggal") or row["tanggal"]
        tipe = f.get("tipe", "keluar")
        if tipe not in ("masuk", "keluar"):
            flash("Jenis transaksi tidak valid.", "danger")
            conn.close()
            return redirect(url_for("pengeluaran_edit", id=id))

        conn.execute("""
            UPDATE pengeluaran
            SET
                tanggal=?,
                tipe=?,
                kategori=?,
                keterangan=?,
                nominal=?
            WHERE id=?
        """, (
            tanggal,
            tipe,
            f.get("kategori"),
            f.get("keterangan"),
            nominal,
            id
        ))
        conn.execute(
            """UPDATE cashflow SET tanggal=?, keterangan=?, tipe=?, nominal=?
               WHERE ref_type='pengeluaran' AND ref_id=?""",
            (tanggal, f"{f.get('kategori')} - {f.get('keterangan') or row['nomor']}", tipe, nominal, id),
        )
        conn.commit()
        conn.close()
        flash("Data pengeluaran berhasil diperbarui.", "success")
        return redirect(url_for("pengeluaran_list"))

    conn.close()
    return render_template("pengeluaran_form.html", row=row, nomor_preview=row["nomor"],
                            kategori_list=KATEGORI_PENGELUARAN)


@app.route("/pengeluaran/hapus/<int:id>", methods=["POST"])
@page_required("pengeluaran")
def pengeluaran_hapus(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM cashflow WHERE ref_type='pengeluaran' AND ref_id=?", (id,))
    conn.execute("DELETE FROM pengeluaran WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash("Data pengeluaran berhasil dihapus.", "success")
    return redirect(url_for("pengeluaran_list"))


# ---------------------------------------------------------------------------
# CASH FLOW
# ---------------------------------------------------------------------------

@app.route("/cashflow")
@page_required("cashflow")
def cashflow_view():
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()

    query = "SELECT * FROM cashflow WHERE 1=1"
    params = []
    if start_date:
        query += " AND tanggal >= ?"; params.append(start_date)
    if end_date:
        query += " AND tanggal <= ?"; params.append(end_date)
    query += " ORDER BY tanggal ASC, id ASC"
    rows = conn.execute(query, params).fetchall()

    saldo_awal = hitung_saldo_awal(start_date)
    if start_date:
        masuk_awal = conn.execute(
            "SELECT COALESCE(SUM(nominal),0) t FROM cashflow WHERE tipe='masuk' AND tanggal < ?",
            (start_date,),
        ).fetchone()["t"]
        keluar_awal = conn.execute(
            "SELECT COALESCE(SUM(nominal),0) t FROM cashflow WHERE tipe='keluar' AND tanggal < ?",
            (start_date,),
        ).fetchone()["t"]
        saldo_awal = masuk_awal - keluar_awal

    saldo = saldo_awal
    data = []
    total_masuk = 0
    total_keluar = 0
    for r in rows:
        if r["tipe"] == "masuk":
            saldo += r["nominal"]
            total_masuk += r["nominal"]
        else:
            saldo -= r["nominal"]
            total_keluar += r["nominal"]
        data.append({
            "tanggal": r["tanggal"], "keterangan": r["keterangan"], "tipe": r["tipe"],
            "nominal": r["nominal"], "saldo": saldo,
        })

    conn.close()

    return render_template("cashflow.html", data=data, use_start=use_start, use_end=use_end, start_date=start_date,
                            end_date=end_date, saldo_awal=saldo_awal, saldo_akhir=saldo, total_masuk=total_masuk,
                            total_keluar=total_keluar)


@app.route("/cashflow/tambah", methods=["GET", "POST"])
@page_required("cashflow")
def cashflow_add():
    if request.method == "POST":
        f = request.form
        tanggal = f.get("tanggal") or datetime.now().strftime("%Y-%m-%d")
        tipe = f.get("tipe")
        keterangan = f.get("keterangan", "").strip()
        nominal = to_float(f.get("nominal"))
        if tipe not in ("masuk", "keluar"):
            flash("Jenis kas tidak valid.", "danger")
            return redirect(url_for("cashflow_add"))
        if nominal <= 0:
            flash("Nominal harus lebih besar dari 0.", "danger")
            return redirect(url_for("cashflow_add"))

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO cashflow (tanggal, keterangan, tipe, nominal) VALUES (?,?,?,?)",
            (tanggal, keterangan, tipe, nominal),
        )
        conn.commit()
        conn.close()
        flash("Transaksi kas berhasil ditambahkan.", "success")
        return redirect(url_for("cashflow_view"))

    return render_template("cashflow_form.html", row=None)


@app.route("/cashflow/edit/<int:id>", methods=["GET", "POST"])
@page_required("cashflow")
def cashflow_edit(id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM cashflow WHERE id=?", (id,)).fetchone()
    if not row:
        conn.close()
        flash("Transaksi kas tidak ditemukan.", "danger")
        return redirect(url_for("cashflow_view"))

    if request.method == "POST":
        f = request.form
        tanggal = f.get("tanggal") or row["tanggal"]
        tipe = f.get("tipe")
        keterangan = f.get("keterangan", "").strip()
        nominal = to_float(f.get("nominal"))
        if tipe not in ("masuk", "keluar"):
            flash("Jenis kas tidak valid.", "danger")
            conn.close()
            return redirect(url_for("cashflow_edit", id=id))
        if nominal <= 0:
            flash("Nominal harus lebih besar dari 0.", "danger")
            conn.close()
            return redirect(url_for("cashflow_edit", id=id))

        conn.execute(
            "UPDATE cashflow SET tanggal=?, keterangan=?, tipe=?, nominal=? WHERE id=?",
            (tanggal, keterangan, tipe, nominal, id),
        )
        conn.commit()
        conn.close()
        flash("Transaksi kas berhasil diperbarui.", "success")
        return redirect(url_for("cashflow_view"))

    conn.close()
    return render_template("cashflow_form.html", row=row)


@app.route("/cashflow/hapus/<int:id>", methods=["POST"])
@page_required("cashflow")
def cashflow_hapus(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM cashflow WHERE id=?", (id,))
    conn.commit()
    conn.close()
    flash("Transaksi kas berhasil dihapus.", "success")
    return redirect(url_for("cashflow_view"))

@app.route("/cashflow/saldo-awal", methods=["GET", "POST"])
@page_required("cashflow")
def saldo_awal_kas():

    conn = get_db_connection()

    if request.method == "POST":
        f = request.form

        nominal = to_float(f.get("nominal"))
        tanggal = f.get("tanggal") or datetime.now().strftime("%Y-%m-%d")
        keterangan = (f.get("keterangan") or "Saldo Awal Kas").strip()

        conn.execute(
            "DELETE FROM cashflow WHERE ref_type='saldo_awal_kas'"
        )

        conn.execute(
            """
            INSERT INTO cashflow
            (tanggal,keterangan,tipe,nominal,ref_type,ref_id)
            VALUES
            (?, ?, 'masuk', ?, 'saldo_awal_kas', NULL)
            """,
            (tanggal, keterangan, nominal)
        )

        conn.commit()
        conn.close()

        flash("Saldo awal berhasil disimpan.", "success")
        return redirect(url_for("saldo_awal_kas"))

    row = conn.execute(
        """
        SELECT *
        FROM cashflow
        WHERE ref_type='saldo_awal_kas'
        LIMIT 1
        """
    ).fetchone()

    conn.close()

    return render_template(
        "saldo_awal.html",
        row=row
    )

@app.route("/cashflow/saldo-awal/hapus", methods=["POST"])
@page_required("cashflow")
def saldo_awal_kas_hapus():

    conn = get_db_connection()

    conn.execute(
        "DELETE FROM cashflow WHERE ref_type='saldo_awal_kas'"
    )

    conn.commit()
    conn.close()

    flash("Saldo awal berhasil dihapus.", "success")

    return redirect(url_for("saldo_awal_kas"))
# ---------------------------------------------------------------------------
# LAPORAN
# ---------------------------------------------------------------------------

@app.route("/laporan")
@page_required("laporan")
def laporan_menu():
    return render_template("laporan_menu.html")


def _laporan_pembelian_data():
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()
    query = "SELECT * FROM laptop WHERE 1=1"
    params = []
    if start_date:
        query += " AND tanggal >= ?"
        params.append(start_date)
    if end_date:
        query += " AND tanggal <= ?"
        params.append(end_date)
    query += " ORDER BY tanggal ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    total = sum(r["total_modal"] for r in rows)
    return rows, total, use_start, use_end, start_date, end_date


@app.route("/laporan/pembelian")
@page_required("laporan")
def laporan_pembelian():
    rows, total, use_start, use_end, start_date, end_date = _laporan_pembelian_data()
    return render_template("laporan_pembelian.html", rows=rows, total=total, use_start=use_start, use_end=use_end,
                            start_date=start_date, end_date=end_date)


@app.route("/laporan/pembelian/pdf")
@page_required("laporan")
def laporan_pembelian_pdf():
    rows, total, use_start, use_end, start_date, end_date = _laporan_pembelian_data()
    headers = ["No. Pembelian", "Tanggal", "Merk/Seri", "Supplier", "Status", "Total Modal"]
    data = [[r["nomor_pembelian"], r["tanggal"], f'{r["merk"]} {r["seri"]}',
             r["supplier"] or "-", r["status"], reports.rp(r["total_modal"])] for r in rows]
    total_row = ["", "", "", "", "TOTAL", reports.rp(total)]
    sub = f"Periode: {start_date or 'Semua'} s/d {end_date or 'Semua'}"
    buf = reports.buat_laporan_pdf("Laporan Pembelian Laptop", sub, headers, data, total_row)
    return send_file(buf, mimetype="application/pdf", download_name="Laporan_Pembelian.pdf")


@app.route("/laporan/pembelian/excel")
@page_required("laporan")
def laporan_pembelian_excel():
    rows, total, use_start, use_end, start_date, end_date = _laporan_pembelian_data()
    headers = ["No. Pembelian", "Tanggal", "Merk", "Seri", "Supplier", "Status", "Total Modal"]
    data = [[r["nomor_pembelian"], r["tanggal"], r["merk"], r["seri"],
             r["supplier"] or "-", r["status"], r["total_modal"]] for r in rows]
    total_row = ["", "", "", "", "", "TOTAL", total]
    buf = reports.buat_laporan_excel("Laporan Pembelian Laptop", headers, data, total_row)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      download_name="Laporan_Pembelian.xlsx")


def _laporan_penjualan_data():
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()
    query = """SELECT p.*, l.merk, l.seri, l.total_modal FROM penjualan p
               JOIN laptop l ON p.laptop_id = l.id WHERE 1=1"""
    params = []
    if start_date:
        query += " AND p.tanggal >= ?"
        params.append(start_date)
    if end_date:
        query += " AND p.tanggal <= ?"
        params.append(end_date)
    query += " ORDER BY p.tanggal ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    total_modal = sum(r["total_modal"] for r in rows)
    total_jual = sum(r["harga_jual"] for r in rows)
    total_laba = sum(r["laba"] for r in rows)
    return rows, total_modal, total_jual, total_laba, use_start, use_end, start_date, end_date


@app.route("/laporan/penjualan")
@page_required("laporan")
def laporan_penjualan():
    rows, total_modal, total_jual, total_laba, use_start, use_end, start_date, end_date = _laporan_penjualan_data()
    return render_template("laporan_penjualan.html", rows=rows, total_modal=total_modal,
                            total_jual=total_jual, total_laba=total_laba, use_start=use_start, use_end=use_end,
                            start_date=start_date, end_date=end_date)


@app.route("/laporan/penjualan/pdf")
@page_required("laporan")
def laporan_penjualan_pdf():
    rows, total_modal, total_jual, total_laba, use_start, use_end, start_date, end_date = _laporan_penjualan_data()
    headers = ["No. Penjualan", "Tanggal", "Laptop", "Pembeli", "Modal", "Harga Jual", "Laba"]
    data = [[r["nomor_penjualan"], r["tanggal"], f'{r["merk"]} {r["seri"]}', r["pembeli"] or "-",
             reports.rp(r["total_modal"]), reports.rp(r["harga_jual"]), reports.rp(r["laba"])]
            for r in rows]
    total_row = ["", "", "", "TOTAL", reports.rp(total_modal), reports.rp(total_jual), reports.rp(total_laba)]
    sub = f"Periode: {start_date or 'Semua'} s/d {end_date or 'Semua'}"
    buf = reports.buat_laporan_pdf("Laporan Penjualan Laptop", sub, headers, data, total_row)
    return send_file(buf, mimetype="application/pdf", download_name="Laporan_Penjualan.pdf")


# @app.route("/laporan/penjualan/excel")
# @page_required("laporan")
# def laporan_penjualan_excel():
#     rows, total_modal, total_jual, total_laba, filt, start_date, end_date = _laporan_penjualan_data()
#     headers = ["No. Penjualan", "Tanggal", "Laptop", "Pembeli", "Modal", "Harga Jual", "Laba"]
#     data = [[r["nomor_penjualan"], r["tanggal"], f'{r["merk"]} {r["seri"]}', r["pembeli"] or "-",
#              r["total_modal"], r["harga_jual"], r["laba"]] for r in rows]
#     total_row = ["", "", "", "TOTAL", total_modal, total_jual, total_laba]
#     buf = reports.buat_laporan_excel("Laporan Penjualan Laptop", headers, data, total_row)
#     return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#                       download_name="Laporan_Penjualan.xlsx")
@app.route("/laporan/penjualan/excel")
@page_required("laporan")
def laporan_penjualan_excel():

    rows, total_modal, total_jual, total_laba, filt, start_date, end_date = _laporan_penjualan_data()

    headers = [
        "No. Penjualan",
        "Tanggal",
        "Laptop",
        "Pembeli",
        "Modal",
        "Harga Jual",
        "Laba"
    ]

    data = [
        [
            r["nomor_penjualan"],
            r["tanggal"],
            f'{r["merk"]} {r["seri"]}',
            r["pembeli"] or "-",
            r["total_modal"],
            r["harga_jual"],
            r["laba"]
        ]
        for r in rows
    ]

    total_row = ["", "", "", "TOTAL", total_modal, total_jual, total_laba]

    buf = reports.buat_laporan_excel(
        "Laporan Penjualan Laptop",
        headers,
        data,
        total_row
    )

    filename = os.path.join(
        os.path.expanduser("~/Documents"),
        "Laporan_Penjualan.xlsx"
    )

    with open(filename, "wb") as f:
        f.write(buf.getvalue())

    os.startfile(filename)

    return jsonify({"success": True})


@app.route("/laporan/stok-ready")
@page_required("laporan")
def laporan_stok_ready():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM laptop WHERE status='Ready' ORDER BY tanggal DESC").fetchall()
    conn.close()
    total = sum(r["total_modal"] for r in rows)
    return render_template("laporan_stok_ready.html", rows=rows, total=total)


@app.route("/laporan/stok-ready/pdf")
@page_required("laporan")
def laporan_stok_ready_pdf():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM laptop WHERE status='Ready' ORDER BY tanggal DESC").fetchall()
    conn.close()
    headers = ["No. Pembelian", "Tanggal", "Merk/Seri", "Kondisi", "Total Modal"]
    data = [[r["nomor_pembelian"], r["tanggal"], f'{r["merk"]} {r["seri"]}', r["kondisi"] or "-",
             reports.rp(r["total_modal"])] for r in rows]
    total_row = ["", "", "", "TOTAL", reports.rp(sum(r["total_modal"] for r in rows))]
    buf = reports.buat_laporan_pdf("Laporan Stok Laptop Ready", "", headers, data, total_row)
    return send_file(buf, mimetype="application/pdf", download_name="Laporan_Stok_Ready.pdf")


@app.route("/laporan/stok-ready/excel")
@page_required("laporan")
def laporan_stok_ready_excel():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM laptop WHERE status='Ready' ORDER BY tanggal DESC").fetchall()
    conn.close()
    headers = ["No. Pembelian", "Tanggal", "Merk", "Seri", "Kondisi", "Total Modal"]
    data = [[r["nomor_pembelian"], r["tanggal"], r["merk"], r["seri"], r["kondisi"] or "-",
             r["total_modal"]] for r in rows]
    buf = reports.buat_laporan_excel("Laporan Stok Laptop Ready", headers, data)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      download_name="Laporan_Stok_Ready.xlsx")


@app.route("/laporan/stok-terjual")
@page_required("laporan")
def laporan_stok_terjual():
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT p.*, l.merk, l.seri, l.total_modal, l.nomor_pembelian FROM penjualan p
           JOIN laptop l ON p.laptop_id = l.id ORDER BY p.tanggal DESC"""
    ).fetchall()
    conn.close()
    return render_template("laporan_stok_terjual.html", rows=rows)


@app.route("/laporan/stok-terjual/pdf")
@page_required("laporan")
def laporan_stok_terjual_pdf():
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT p.*, l.merk, l.seri, l.total_modal FROM penjualan p
           JOIN laptop l ON p.laptop_id = l.id ORDER BY p.tanggal DESC"""
    ).fetchall()
    conn.close()
    headers = ["No. Penjualan", "Tanggal", "Laptop", "Pembeli", "Harga Jual", "Laba"]
    data = [[r["nomor_penjualan"], r["tanggal"], f'{r["merk"]} {r["seri"]}', r["pembeli"] or "-",
             reports.rp(r["harga_jual"]), reports.rp(r["laba"])] for r in rows]
    buf = reports.buat_laporan_pdf("Laporan Riwayat Laptop Terjual", "", headers, data)
    return send_file(buf, mimetype="application/pdf", download_name="Laporan_Terjual.pdf")


@app.route("/laporan/stok-terjual/excel")
@page_required("laporan")
def laporan_stok_terjual_excel():
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT p.*, l.merk, l.seri, l.total_modal FROM penjualan p
           JOIN laptop l ON p.laptop_id = l.id ORDER BY p.tanggal DESC"""
    ).fetchall()
    conn.close()
    headers = ["No. Penjualan", "Tanggal", "Laptop", "Pembeli", "Harga Jual", "Laba"]
    data = [[r["nomor_penjualan"], r["tanggal"], f'{r["merk"]} {r["seri"]}', r["pembeli"] or "-",
             r["harga_jual"], r["laba"]] for r in rows]
    buf = reports.buat_laporan_excel("Laporan Riwayat Laptop Terjual", headers, data)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      download_name="Laporan_Terjual.xlsx")


def _laporan_pengeluaran_data():
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()
    query = "SELECT * FROM pengeluaran WHERE 1=1"
    params = []
    if start_date:
        query += " AND tanggal >= ?"
        params.append(start_date)
    if end_date:
        query += " AND tanggal <= ?"
        params.append(end_date)
    query += " ORDER BY tanggal ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    total = sum(r["nominal"] for r in rows)
    return rows, total, use_start, use_end, start_date, end_date


@app.route("/laporan/pengeluaran")
@page_required("laporan")
def laporan_pengeluaran():
    rows, total, use_start, use_end, start_date, end_date = _laporan_pengeluaran_data()
    return render_template("laporan_pengeluaran.html", rows=rows, total=total, use_start=use_start, use_end=use_end,
                            start_date=start_date, end_date=end_date)


@app.route("/laporan/pengeluaran/pdf")
@page_required("laporan")
def laporan_pengeluaran_pdf():
    rows, total, use_start, use_end, start_date, end_date = _laporan_pengeluaran_data()
    headers = ["Nomor", "Tanggal", "Kategori", "Keterangan", "Nominal"]
    data = [[r["nomor"], r["tanggal"], r["kategori"], r["keterangan"] or "-",
             reports.rp(r["nominal"])] for r in rows]
    total_row = ["", "", "", "TOTAL", reports.rp(total)]
    sub = f"Periode: {start_date or 'Semua'} s/d {end_date or 'Semua'}"
    buf = reports.buat_laporan_pdf("Laporan Pengeluaran", sub, headers, data, total_row)
    return send_file(buf, mimetype="application/pdf", download_name="Laporan_Pengeluaran.pdf")


@app.route("/laporan/pengeluaran/excel")
@page_required("laporan")
def laporan_pengeluaran_excel():
    rows, total, filt, start_date, end_date = _laporan_pengeluaran_data()
    headers = ["Nomor", "Tanggal", "Kategori", "Keterangan", "Nominal"]
    data = [[r["nomor"], r["tanggal"], r["kategori"], r["keterangan"] or "-", r["nominal"]] for r in rows]
    total_row = ["", "", "", "TOTAL", total]
    buf = reports.buat_laporan_excel("Laporan Pengeluaran", headers, data, total_row)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      download_name="Laporan_Pengeluaran.xlsx")


@app.route("/laporan/cashflow")
@page_required("laporan")
def laporan_cashflow():
    return redirect(url_for("cashflow_view", **request.args))


@app.route("/laporan/cashflow/pdf")
@page_required("laporan")
def laporan_cashflow_pdf():
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()
    query = "SELECT * FROM cashflow WHERE 1=1"
    params = []
    if start_date:
        query += " AND tanggal >= ?"
        params.append(start_date)
    if end_date:
        query += " AND tanggal <= ?"
        params.append(end_date)
    query += " ORDER BY tanggal ASC, id ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    saldo = 0
    headers = ["Tanggal", "Keterangan", "Kas Masuk", "Kas Keluar", "Saldo"]
    data = []
    for r in rows:
        masuk = r["nominal"] if r["tipe"] == "masuk" else 0
        keluar = r["nominal"] if r["tipe"] == "keluar" else 0
        saldo += masuk - keluar
        data.append([r["tanggal"], r["keterangan"], reports.rp(masuk) if masuk else "-",
                     reports.rp(keluar) if keluar else "-", reports.rp(saldo)])
    sub = f"Periode: {start_date or 'Semua'} s/d {end_date or 'Semua'}"
    buf = reports.buat_laporan_pdf("Laporan Cash Flow", sub, headers, data)
    return send_file(buf, mimetype="application/pdf", download_name="Laporan_CashFlow.pdf")


@app.route("/laporan/cashflow/excel")
@page_required("laporan")
def laporan_cashflow_excel():
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()
    query = "SELECT * FROM cashflow WHERE 1=1"
    params = []
    if start_date:
        query += " AND tanggal >= ?"
        params.append(start_date)
    if end_date:
        query += " AND tanggal <= ?"
        params.append(end_date)
    query += " ORDER BY tanggal ASC, id ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()

    saldo = 0
    headers = ["Tanggal", "Keterangan", "Kas Masuk", "Kas Keluar", "Saldo"]
    data = []
    for r in rows:
        masuk = r["nominal"] if r["tipe"] == "masuk" else 0
        keluar = r["nominal"] if r["tipe"] == "keluar" else 0
        saldo += masuk - keluar
        data.append([r["tanggal"], r["keterangan"], masuk, keluar, saldo])
    buf = reports.buat_laporan_excel("Laporan Cash Flow", headers, data)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      download_name="Laporan_CashFlow.xlsx")


def _laba_rugi_data():
    use_start, use_end, start_date, end_date = get_period_range()
    conn = get_db_connection()

    q_jual = "SELECT COALESCE(SUM(harga_jual),0) t FROM penjualan WHERE 1=1"
    q_modal = "SELECT COALESCE(SUM(total_modal),0) t FROM laptop WHERE 1=1"
    q_beban = "SELECT COALESCE(SUM(nominal),0) t FROM pengeluaran WHERE 1=1"
    params_jual, params_modal, params_beban = [], [], []

    if start_date:
        q_jual += " AND tanggal >= ?"; params_jual.append(start_date)
        q_modal += " AND tanggal >= ?"; params_modal.append(start_date)
        q_beban += " AND tanggal >= ?"; params_beban.append(start_date)
    if end_date:
        q_jual += " AND tanggal <= ?"; params_jual.append(end_date)
        q_modal += " AND tanggal <= ?"; params_modal.append(end_date)
        q_beban += " AND tanggal <= ?"; params_beban.append(end_date)

    pendapatan = conn.execute(q_jual, params_jual).fetchone()["t"]
    modal = conn.execute(q_modal, params_modal).fetchone()["t"]
    beban = conn.execute(q_beban, params_beban).fetchone()["t"]
    conn.close()

    laba_bersih = pendapatan - modal - beban
    return pendapatan, modal, beban, laba_bersih, use_start, use_end, start_date, end_date


@app.route("/laporan/laba-rugi")
@page_required("laporan")
def laporan_laba_rugi():
    pendapatan, modal, beban, laba_bersih, use_start, use_end, start_date, end_date = _laba_rugi_data()
    return render_template("laporan_labarugi.html", pendapatan=pendapatan, modal=modal,
                            beban=beban, laba_bersih=laba_bersih, use_start=use_start, use_end=use_end,
                            start_date=start_date, end_date=end_date)


@app.route("/laporan/laba-rugi/pdf")
@page_required("laporan")
def laporan_laba_rugi_pdf():
    pendapatan, modal, beban, laba_bersih, filt, start_date, end_date = _laba_rugi_data()
    headers = ["Keterangan", "Nominal"]
    data = [
        ["Pendapatan (Total Penjualan)", reports.rp(pendapatan)],
        ["Modal (Total Harga Beli)", reports.rp(modal)],
        ["Pengeluaran Operasional", reports.rp(beban)],
    ]
    total_row = ["LABA BERSIH", reports.rp(laba_bersih)]
    sub = f"Periode: {start_date or 'Semua'} s/d {end_date or 'Semua'}"
    buf = reports.buat_laporan_pdf("Laporan Laba Rugi", sub, headers, data, total_row)
    return send_file(buf, mimetype="application/pdf", download_name="Laporan_Laba_Rugi.pdf")


@app.route("/laporan/laba-rugi/excel")
@page_required("laporan")
def laporan_laba_rugi_excel():
    pendapatan, modal, beban, laba_bersih, filt, start_date, end_date = _laba_rugi_data()
    headers = ["Keterangan", "Nominal"]
    data = [
        ["Pendapatan (Total Penjualan)", pendapatan],
        ["Modal (Total Harga Beli)", modal],
        ["Pengeluaran Operasional", beban],
    ]
    total_row = ["LABA BERSIH", laba_bersih]
    buf = reports.buat_laporan_excel("Laporan Laba Rugi", headers, data, total_row)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      download_name="Laporan_Laba_Rugi.xlsx")


# ---------------------------------------------------------------------------
# PENGGUNA (Admin)
# ---------------------------------------------------------------------------

@app.route("/pengguna")
@page_required("pengguna")
def pengguna_list():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM users WHERE role != 'root' ORDER BY id ASC").fetchall()
    conn.close()
    return render_template("pengguna_list.html", rows=rows)


@app.route("/pengguna/tambah", methods=["GET", "POST"])
@page_required("pengguna")
def pengguna_tambah():
    allowed_roles = allowed_roles_for(session.get("role"))
    if request.method == "POST":
        f = request.form
        username = f.get("username", "").strip()
        password = f.get("password", "")
        role = f.get("role", "admin")
        if role not in [r[0] for r in allowed_roles]:
            flash("Role pengguna tidak valid.", "danger")
            return redirect(url_for("pengguna_tambah"))

        conn = get_db_connection()
        existing = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            flash("Username sudah digunakan.", "danger")
        elif len(password) < 4:
            flash("Password minimal 4 karakter.", "danger")
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, nama, role) VALUES (?,?,?,?)",
                (username, generate_password_hash(password), f.get("nama"), role),
            )
            conn.commit()
            conn.close()
            flash("Pengguna baru berhasil ditambahkan.", "success")
            return redirect(url_for("pengguna_list"))
        conn.close()

    return render_template("pengguna_form.html", row=None, allowed_roles=allowed_roles)


@app.route("/pengguna/edit/<int:id>", methods=["GET", "POST"])
@page_required("pengguna")
def pengguna_edit(id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE id=?", (id,)).fetchone()
    if not row:
        conn.close()
        flash("Pengguna tidak ditemukan.", "danger")
        return redirect(url_for("pengguna_list"))
    if row["role"] == "root":
        conn.close()
        flash("Akun Root tidak dapat diubah melalui menu ini.", "danger")
        return redirect(url_for("pengguna_list"))

    allowed_roles = allowed_roles_for(session.get("role"))
    if request.method == "POST":
        f = request.form
        nama = f.get("nama")
        password = f.get("password", "")
        role = f.get("role", row["role"])
        if role not in [r[0] for r in allowed_roles]:
            flash("Role pengguna tidak valid.", "danger")
            conn.close()
            return redirect(url_for("pengguna_edit", id=id))

        if password:
            conn.execute(
                "UPDATE users SET nama=?, role=?, password_hash=? WHERE id=?",
                (nama, role, generate_password_hash(password), id),
            )
        else:
            conn.execute("UPDATE users SET nama=?, role=? WHERE id=?", (nama, role, id))
        conn.commit()
        conn.close()
        flash("Data pengguna berhasil diperbarui.", "success")
        return redirect(url_for("pengguna_list"))

    conn.close()
    return render_template("pengguna_form.html", row=row, allowed_roles=allowed_roles)


@app.route("/pengguna/hapus/<int:id>", methods=["POST"])
@page_required("pengguna")
def pengguna_hapus(id):
    if id == session.get("user_id"):
        flash("Tidak dapat menghapus akun yang sedang digunakan.", "danger")
        return redirect(url_for("pengguna_list"))
    conn = get_db_connection()
    row = conn.execute("SELECT role FROM users WHERE id=?", (id,)).fetchone()
    if row and row["role"] == "root":
        flash("Akun Root tidak dapat dihapus.", "danger")
        conn.close()
        return redirect(url_for("pengguna_list"))
    total = conn.execute("SELECT COUNT(*) c FROM users WHERE role != 'root'").fetchone()["c"]
    if total <= 1:
        flash("Minimal harus ada satu pengguna admin.", "danger")
    else:
        conn.execute("DELETE FROM users WHERE id=?", (id,))
        conn.execute("DELETE FROM page_access WHERE user_id=?", (id,))
        conn.commit()
        flash("Pengguna berhasil dihapus.", "success")
    conn.close()
    return redirect(url_for("pengguna_list"))

# def open_browser():
#     webbrowser.open("http://127.0.0.1:5000")
    
# ---------------------------------------------------------------------------
# KONFIGURASI APLIKASI (Root only) - judul & warna tema
# ---------------------------------------------------------------------------

@app.route("/konfigurasi", methods=["GET", "POST"])
@root_required
def konfigurasi():
    if request.method == "POST":
        f = request.form
        settings_updates = {
            "app_title": f.get("app_title", "LaptopBekasApp").strip() or "LaptopBekasApp",
            "company_name": f.get("company_name", "LaptopBekasApp").strip() or "LaptopBekasApp",
            "company_address": f.get("company_address", "").strip(),
            "company_contact": f.get("company_contact", "").strip(),
            "login_title": f.get("login_title", "").strip(),
            "login_icon": f.get("login_icon", "bi bi-laptop").strip() or "bi bi-laptop",
            "color_primary": f.get("color_primary", "#0d6efd"),
            "color_sidebar": f.get("color_sidebar", "#0b3d91"),
        }

        logo_file = request.files.get("login_logo")
        if logo_file and logo_file.filename:
            allowed_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
            filename = secure_filename(logo_file.filename)
            ext = os.path.splitext(filename)[1].lower()
            if ext in allowed_ext:
                upload_dir = os.path.join(app.root_path, "static", "uploads")
                os.makedirs(upload_dir, exist_ok=True)
                saved_name = f"login_logo{ext}"
                logo_file.save(os.path.join(upload_dir, saved_name))
                settings_updates["login_logo"] = saved_name
            else:
                flash("Tipe file tidak didukung. Gunakan PNG, JPG, JPEG, GIF, atau WEBP.", "danger")
                return redirect(url_for("konfigurasi"))

        update_settings(settings_updates)
        flash("Konfigurasi aplikasi berhasil disimpan.", "success")
        return redirect(url_for("konfigurasi"))

    return render_template("konfigurasi.html", settings=get_all_settings())


# ---------------------------------------------------------------------------
# HAK AKSES HALAMAN (Root only)
# ---------------------------------------------------------------------------

@app.route("/hak-akses", methods=["GET", "POST"])
@root_required
def hak_akses():
    if request.method == "POST":
        save_access_matrix(request.form)
        flash("Hak akses pengguna berhasil diperbarui.", "success")
        return redirect(url_for("hak_akses"))

    return render_template("hak_akses.html", matrix=get_access_matrix(), page_list=PAGE_LIST)


# ---------------------------------------------------------------------------
# PROFIL SAYA (ganti password sendiri, termasuk untuk akun Root)
# ---------------------------------------------------------------------------

@app.route("/profil", methods=["GET", "POST"])
@login_required
def profil():
    conn = get_db_connection()
    if request.method == "POST":
        f = request.form
        nama = f.get("nama")
        password = f.get("password", "")
        if password:
            conn.execute(
                "UPDATE users SET nama=?, password_hash=? WHERE id=?",
                (nama, generate_password_hash(password), session["user_id"]),
            )
            flash("Profil dan password berhasil diperbarui.", "success")
        else:
            conn.execute("UPDATE users SET nama=? WHERE id=?", (nama, session["user_id"]))
            flash("Profil berhasil diperbarui.", "success")
        conn.commit()
        session["nama"] = nama
        conn.close()
        return redirect(url_for("profil"))

    row = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return render_template("profil.html", row=row)


# ---------------------------------------------------------------------------
# API kecil untuk detail laptop (dipakai form penjualan, tanpa API eksternal)
# ---------------------------------------------------------------------------

@app.route("/api/laptop/<int:id>")
@page_required("penjualan")
def api_laptop_detail(id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM laptop WHERE id=?", (id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)