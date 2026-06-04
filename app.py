"""
ESP8266 Cloud Relay — Flask backend pentru Render
Arhitectura: Browser <-> Flask (Render) <-> ESP8266 (polling)
Persistență: PostgreSQL (Render free tier)
"""

import os, threading
from datetime import datetime, timezone
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from flask import Flask, request, jsonify, send_from_directory
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__, static_folder="static")

# ── CONFIG (setezi în Render > Environment) ───────────────────
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
SENDER_EMAIL     = os.environ.get("SENDER_EMAIL", "")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")
API_KEY     = os.environ.get("API_KEY", "changeme")
DATABASE_URL = os.environ.get("DATABASE_URL", "")  # automat de Render

# ── DB HELPERS ────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id        SERIAL PRIMARY KEY,
                    text      TEXT NOT NULL,
                    ts        TEXT NOT NULL,
                    delivered BOOLEAN DEFAULT FALSE
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS floods (
                    id    SERIAL PRIMARY KEY,
                    ts    TEXT NOT NULL,
                    value TEXT NOT NULL
                );
            """)
        conn.commit()

# ── HELPERS ───────────────────────────────────────────────────

def now_ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def send_email_async(subject, body):
    def _send():
        if not SENDGRID_API_KEY or not ALERT_EMAIL:
            print("[EMAIL] Credențiale lipsă.")
            return
        try:
            msg = Mail(
                from_email=SENDER_EMAIL,
                to_emails=ALERT_EMAIL,
                subject=subject,
                plain_text_content=body
            )
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            sg.send(msg)
            print(f"[EMAIL] Trimis OK")
        except Exception as e:
            print(f"[EMAIL] Eroare: {e}")
    threading.Thread(target=_send, daemon=True).start()

def check_api_key():
    key = request.headers.get("X-API-Key") or request.args.get("key")
    return key == API_KEY

# ── RUTE ESP (polling de pe ESP) ──────────────────────────────

@app.route("/esp/messages/pending")
def esp_get_pending():
    if not check_api_key():
        return jsonify({"error": "unauthorized"}), 401

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, text FROM messages WHERE delivered = FALSE ORDER BY id")
            pending = cur.fetchall()
            if pending:
                ids = [m["id"] for m in pending]
                cur.execute("UPDATE messages SET delivered = TRUE WHERE id = ANY(%s)", (ids,))
        conn.commit()

    return jsonify({"messages": [m["text"] for m in pending]})


@app.route("/esp/flood", methods=["POST"])
def esp_flood_event():
    if not check_api_key():
        return jsonify({"error": "unauthorized"}), 401

    data  = request.get_json(silent=True) or {}
    value = str(data.get("value", "?"))
    ts    = now_ts()
    print(f"[FLOOD] Primit! value={value} GMAIL_USER={GMAIL_USER} ALERT_EMAIL={ALERT_EMAIL}")  # adaugă ast
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Păstrează ultimele 10
            cur.execute("INSERT INTO floods (ts, value) VALUES (%s, %s)", (ts, value))
            cur.execute("""
                DELETE FROM floods WHERE id NOT IN (
                    SELECT id FROM floods ORDER BY id DESC LIMIT 10
                )
            """)
        conn.commit()

    send_email_async(
        subject=f"⚠️ FLOOD DETECTED — {ts}",
        body=f"Senzorul de inundație a detectat apă.\n\nValoare ADC: {value}\nTimestamp: {ts}\n\nVerifică sistemul!"
    )

    return jsonify({"status": "ok", "ts": ts})


# ── RUTE BROWSER (UI) ─────────────────────────────────────────

@app.route("/api/messages", methods=["GET"])
def api_get_messages():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM messages ORDER BY id")
            return jsonify(cur.fetchall())


@app.route("/api/messages", methods=["POST"])
def api_send_message():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO messages (text, ts) VALUES (%s, %s)", (text, now_ts()))
            # Păstrează ultimele 10
            cur.execute("""
                DELETE FROM messages WHERE id NOT IN (
                    SELECT id FROM messages ORDER BY id DESC LIMIT 10
                )
            """)
        conn.commit()

    return jsonify({"status": "queued"})


@app.route("/api/messages/<int:msg_id>", methods=["DELETE"])
def api_delete_message(msg_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM messages WHERE id = %s", (msg_id,))
        conn.commit()
    return jsonify({"status": "deleted"})


@app.route("/api/floods", methods=["GET"])
def api_get_floods():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM floods ORDER BY id")
            return jsonify(cur.fetchall())


@app.route("/api/floods/<int:flood_id>", methods=["DELETE"])
def api_delete_flood(flood_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM floods WHERE id = %s", (flood_id,))
        conn.commit()
    return jsonify({"status": "deleted"})


@app.route("/api/status")
def api_status():
    return jsonify({"status": "online", "ts": now_ts()})


# ── SERVIRE FRONTEND STATIC ───────────────────────────────────

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    if path and os.path.exists(os.path.join("static", path)):
        return send_from_directory("static", path)
    return send_from_directory("static", "index.html")


# ── INIT ──────────────────────────────────────────────────────

with app.app_context():
    if DATABASE_URL:
        init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
