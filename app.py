import socket
import qrcode
from io import BytesIO
from flask import send_file
import os
import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session
from werkzeug.utils import secure_filename
from PyPDF2 import PdfReader

from services.printer import print_file


APP_NAME = "Akash Digital PrintHub"
DB_PATH = "printhub.db"
UPLOAD_FOLDER = "uploads"
ALLOWED_EXT = {"pdf", "jpg", "jpeg", "png", "doc", "docx"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = "change-this-secret"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password")

        if password == "1234":
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))

        return render_template("login.html", error="Wrong password")

    return render_template("login.html")
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

DEFAULT_SERVICES = {
    "bw_single": {"name": "B/W A4 Single Side", "rate": 5, "printer": "Kyocera FS-1025MFP GX"},
    "bw_double": {"name": "B/W A4 Double Side", "rate": 7, "printer": "Kyocera FS-1025MFP GX"},
    "color_single": {"name": "Color A4 Single Side", "rate": 10, "printer": "EPSON L3210 Series"},
    "color_double": {"name": "Color A4 Double Side", "rate": 20, "printer": "EPSON L3210 Series"},
    "id_card": {"name": "ID Card Print", "rate": 5, "printer": "EPSON L3210 Series"},
}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE,
        name TEXT,
        mobile TEXT,
        service_key TEXT,
        service_name TEXT,
        rate INTEGER,
        pages INTEGER,
        copies INTEGER,
        total INTEGER,
        payment_mode TEXT,
        payment_status TEXT DEFAULT 'Unpaid',
        order_status TEXT DEFAULT 'Pending',
        notes TEXT,
        suggested_printer TEXT,
        created_at TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        original_name TEXT,
        saved_name TEXT,
        pages INTEGER,
        ext TEXT,
        FOREIGN KEY(order_id) REFERENCES orders(id)
    )
    """)

    if not conn.execute("SELECT value FROM settings WHERE key='services'").fetchone():
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('services',?)",
            (json.dumps(DEFAULT_SERVICES),)
        )

    conn.commit()
    conn.close()


init_db()


def get_services():
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key='services'").fetchone()
    conn.close()
    return json.loads(row["value"]) if row else DEFAULT_SERVICES


def allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def count_pages(filepath, ext):
    if ext == "pdf":
        try:
            return len(PdfReader(filepath).pages)
        except Exception:
            return 1
    return 1


def make_token():
    return "ADP" + datetime.now().strftime("%H%M%S")


@app.route("/")
def index():
    return render_template("index.html", app_name=APP_NAME, services=get_services())


@app.route("/submit", methods=["POST"])
def submit():
    services = get_services()
    service_key = request.form.get("service")

    if service_key not in services:
        flash("Invalid service selected")
        return redirect(url_for("index"))

    uploaded = request.files.getlist("documents")
    uploaded = [f for f in uploaded if f and f.filename]

    if not uploaded:
        flash("किमान एक file upload करा")
        return redirect(url_for("index"))

    total_pages = 0
    saved_files = []

    for f in uploaded:
        if not allowed(f.filename):
            continue

        original = secure_filename(f.filename)
        ext = original.rsplit(".", 1)[1].lower()
        saved = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}_{original}"
        path = os.path.join(UPLOAD_FOLDER, saved)

        f.save(path)

        pages = count_pages(path, ext)
        total_pages += pages
        saved_files.append((original, saved, pages, ext))

    if not saved_files:
        flash("Allowed files: PDF, JPG, PNG, DOC, DOCX")
        return redirect(url_for("index"))

    service = services[service_key]
    copies = max(1, int(request.form.get("copies", 1)))
    rate = int(service["rate"])
    total = total_pages * copies * rate
    payment_mode = request.form.get("payment", "Pay at Shop")
    payment_status = "Unpaid" if payment_mode == "Pay at Shop" else "Payment Pending"

    conn = db()

    cur = conn.execute(
        """INSERT INTO orders
        (token,name,mobile,service_key,service_name,rate,pages,copies,total,payment_mode,payment_status,notes,suggested_printer,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            make_token(),
            request.form.get("name", ""),
            request.form.get("mobile", ""),
            service_key,
            service["name"],
            rate,
            total_pages,
            copies,
            total,
            payment_mode,
            payment_status,
            request.form.get("notes", ""),
            service["printer"],
            datetime.now().strftime("%d-%m-%Y %I:%M %p"),
        ),
    )

    order_id = cur.lastrowid

    for original, saved, pages, ext in saved_files:
        conn.execute(
            "INSERT INTO files(order_id,original_name,saved_name,pages,ext) VALUES(?,?,?,?,?)",
            (order_id, original, saved, pages, ext),
        )

    conn.commit()

    try:
        first_file = conn.execute(
            "SELECT * FROM files WHERE order_id=? LIMIT 1",
            (order_id,),
        ).fetchone()

        if first_file:
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], first_file["saved_name"])
            print_file(file_path, service_key)

    except Exception as e:
        print("AUTO PRINT DIALOG ERROR:", e)

    conn.close()

    return redirect(url_for("success", order_id=order_id))


@app.route("/success/<int:order_id>")
def success(order_id):
    conn = db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    files = conn.execute("SELECT * FROM files WHERE order_id=?", (order_id,)).fetchall()
    conn.close()
    return render_template("success.html", order=order, files=files)


@app.route("/order-count")
def order_count():
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM orders WHERE order_status!='Deleted'").fetchone()["c"]
    conn.close()
    return {"count": count}
@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))
    conn = db()
    orders = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    total = conn.execute("SELECT COALESCE(SUM(total),0) AS s FROM orders WHERE order_status!='Deleted'").fetchone()["s"]
    pending = conn.execute("SELECT COUNT(*) AS c FROM orders WHERE order_status='Pending'").fetchone()["c"]
    conn.close()
    return render_template("admin.html", orders=orders, total=total, pending=pending)
@app.route("/reports")
def reports():
    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))
    selected_date = request.args.get("date")
    selected_status = request.args.get("status", "all")

    conn = db()

    if not selected_date:
        selected_date = conn.execute(
            "SELECT DATE('now', 'localtime') AS d"
        ).fetchone()["d"]

    date_expr = "substr(created_at, 7, 4) || '-' || substr(created_at, 4, 2) || '-' || substr(created_at, 1, 2)"

    report = conn.execute(f"""
        SELECT COUNT(*) AS total_orders,
               COALESCE(SUM(total), 0) AS total_income
        FROM orders
        WHERE {date_expr} = ?
    """, (selected_date,)).fetchone()

    pending = conn.execute(f"""
        SELECT COUNT(*) AS c
        FROM orders
        WHERE {date_expr} = ?
        AND order_status = 'Pending'
    """, (selected_date,)).fetchone()["c"]

    completed = conn.execute(f"""
        SELECT COUNT(*) AS c
        FROM orders
        WHERE {date_expr} = ?
        AND order_status = 'Completed'
    """, (selected_date,)).fetchone()["c"]

    status_condition = ""
    if selected_status == "pending":
        status_condition = "AND order_status = 'Pending'"
    elif selected_status == "completed":
        status_condition = "AND order_status = 'Completed'"

    orders_list = conn.execute(f"""
        SELECT *
        FROM orders
        WHERE {date_expr} = ?
        {status_condition}
        ORDER BY id DESC
    """, (selected_date,)).fetchall()

    conn.close()

    return render_template(
        "reports.html",
        today=report,
        pending=pending,
        completed=completed,
        selected_date=selected_date,
        selected_status=selected_status,
        orders=orders_list
    )
@app.route("/order/<int:order_id>")
def order_detail(order_id):
    conn = db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    files = conn.execute("SELECT * FROM files WHERE order_id=?", (order_id,)).fetchall()
    conn.close()
    return render_template("order_detail.html", order=order, files=files)


@app.route("/uploads/<path:filename>")
def uploaded(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/paid/<int:order_id>")
def mark_paid(order_id):
    conn = db()
    conn.execute("UPDATE orders SET payment_status='Paid' WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for("admin"))


@app.route("/complete/<int:order_id>")
def complete(order_id):
    conn = db()
    conn.execute("UPDATE orders SET order_status='Completed' WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/delete/<int:order_id>")
def delete(order_id):
    conn = db()
    conn.execute("UPDATE orders SET order_status='Deleted' WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))
    services = get_services()

    if request.method == "POST":
        for key in services:
            services[key]["rate"] = int(request.form.get(f"rate_{key}", services[key]["rate"]))

        conn = db()
        conn.execute("UPDATE settings SET value=? WHERE key='services'", (json.dumps(services),))
        conn.commit()
        conn.close()

        flash("Rates updated")
        return redirect(url_for("settings"))

    return render_template("settings.html", services=services)

def get_local_ip():
    try:
        return socket.gethostbyname(socket.gethostname())
    except:
        return "127.0.0.1"


@app.route("/qr")
def qr_page():
    ip = get_local_ip()
    upload_url = f"http://{ip}:5000"
    return render_template("qr.html", upload_url=upload_url)


@app.route("/qr-image")
def qr_image():
    ip = get_local_ip()
    upload_url = f"http://{ip}:5000"

    img = qrcode.make(upload_url)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return send_file(buffer, mimetype="image/png")
@app.route("/print/<int:order_id>")
def print_order(order_id):
    conn = db()

    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    file = conn.execute("SELECT * FROM files WHERE order_id=? LIMIT 1", (order_id,)).fetchone()

    conn.close()

    if not order:
        return "Order not found"

    if not file:
        return "File not found for this order"

    service = order["service_key"]
    filename = file["saved_name"]
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    try:
        printer_used = print_file(file_path, service)
        return f"Print dialog opened for {printer_used}"
    except Exception as e:
        return f"Print failed: {e}"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)