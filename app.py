from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
from PyPDF2 import PdfReader
import os, sqlite3, time

APP_NAME = "Akash Digital PrintHub"
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "docx", "doc"}

RATES = {
    "bw_single": {"label": "B/W A4 Single Side", "rate": 5, "printer": "Kyocera FS-1025MFP GX"},
    "bw_double": {"label": "B/W A4 Double Side", "rate": 7, "printer": "Kyocera FS-1025MFP GX"},
    "color_single": {"label": "Color A4 Single Side", "rate": 10, "printer": "EPSON L3210 Series"},
    "color_double": {"label": "Color A4 Double Side", "rate": 20, "printer": "EPSON L3210 Series"},
    "id_card": {"label": "ID Card Print", "rate": 5, "printer": "EPSON L3210 Series"},
}

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def count_pdf_pages(path):
    try:
        reader = PdfReader(path)
        return len(reader.pages)
    except Exception:
        return 1


def get_db():
    conn = sqlite3.connect("printhub.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        mobile TEXT NOT NULL,
        service_key TEXT NOT NULL,
        service_label TEXT NOT NULL,
        rate INTEGER NOT NULL,
        copies INTEGER NOT NULL,
        pages INTEGER NOT NULL,
        total INTEGER NOT NULL,
        payment_mode TEXT NOT NULL,
        payment_status TEXT NOT NULL,
        notes TEXT,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        original_name TEXT NOT NULL,
        pages INTEGER NOT NULL
    )
    """)
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def index():
    return render_template("index.html", rates=RATES, app_name=APP_NAME)

@app.route("/submit", methods=["POST"])
def submit_order():
    name = request.form.get("name", "").strip()
    mobile = request.form.get("mobile", "").strip()
    service_key = request.form.get("service")
    copies = int(request.form.get("copies", 1) or 1)
    payment_mode = request.form.get("payment_mode", "Pay at Shop")
    notes = request.form.get("notes", "")

    if service_key not in RATES:
        return "Invalid service", 400

    files = request.files.getlist("documents")
    saved_files = []
    total_pages = 0
    timestamp = str(int(time.time()))

    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_file(f.filename):
            continue
        original = f.filename
        safe = secure_filename(original)
        filename = f"{timestamp}_{safe}"
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        f.save(path)
        ext = filename.rsplit('.', 1)[1].lower()
        pages = count_pdf_pages(path) if ext == 'pdf' else 1
        total_pages += pages
        saved_files.append((filename, original, pages))

    if not saved_files:
        return "कृपया किमान 1 file upload करा", 400

    rate_data = RATES[service_key]
    rate = rate_data["rate"]
    if service_key == "id_card":
        total = rate * copies
        total_pages = max(1, total_pages)
    else:
        total = total_pages * rate * copies

    payment_status = "Paid" if payment_mode == "Pay Now UPI" else "Unpaid"

    conn = get_db()
    cur = conn.execute("""
        INSERT INTO orders (name, mobile, service_key, service_label, rate, copies, pages, total,
        payment_mode, payment_status, notes, created_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'), ?)
    """, (name, mobile, service_key, rate_data["label"], rate, copies, total_pages, total,
          payment_mode, payment_status, notes, "Pending"))
    order_id = cur.lastrowid
    for filename, original, pages in saved_files:
        conn.execute("INSERT INTO files (order_id, filename, original_name, pages) VALUES (?, ?, ?, ?)",
                     (order_id, filename, original, pages))
    conn.commit()
    conn.close()
    return redirect(url_for("success", order_id=order_id))

@app.route("/success/<int:order_id>")
def success(order_id):
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    conn.close()
    return render_template("success.html", order=order, app_name=APP_NAME)

@app.route("/admin")
def admin():
    conn = get_db()
    orders = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    files_by_order = {}
    for o in orders:
        files_by_order[o["id"]] = conn.execute("SELECT * FROM files WHERE order_id=?", (o["id"],)).fetchall()
    conn.close()
    return render_template("admin.html", orders=orders, files_by_order=files_by_order, rates=RATES, app_name=APP_NAME)

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/mark-paid/<int:order_id>")
def mark_paid(order_id):
    conn = get_db()
    conn.execute("UPDATE orders SET payment_status='Paid' WHERE id=?", (order_id,))
    conn.commit(); conn.close()
    return redirect(url_for("admin"))

@app.route("/complete/<int:order_id>")
def complete(order_id):
    conn = get_db()
    conn.execute("UPDATE orders SET status='Completed' WHERE id=?", (order_id,))
    conn.commit(); conn.close()
    return redirect(url_for("admin"))

@app.route("/delete/<int:order_id>")
def delete(order_id):
    conn = get_db()
    files = conn.execute("SELECT filename FROM files WHERE order_id=?", (order_id,)).fetchall()
    for f in files:
        try: os.remove(os.path.join(app.config["UPLOAD_FOLDER"], f["filename"]))
        except Exception: pass
    conn.execute("DELETE FROM files WHERE order_id=?", (order_id,))
    conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
    conn.commit(); conn.close()
    return redirect(url_for("admin"))

@app.route("/print-info/<int:order_id>")
def print_info(order_id):
    conn = get_db(); order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone(); conn.close()
    printer = RATES[order["service_key"]]["printer"]
    return f"Suggested Printer: {printer}. Direct print agent पुढच्या version मध्ये add होईल."

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
