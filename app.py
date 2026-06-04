"""
ESP8266 Cloud Relay — Flask backend pentru Render
Arhitectura: Browser <-> Flask (Render) <-> ESP8266 (polling)
"""

import os, json, smtplib, threading
from datetime import datetime, timezone
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

# ── CONFIG (setezi în Render > Environment) ───────────────────
GMAIL_USER    = os.environ.get("GMAIL_USER", "")       # ex: tine@gmail.com
GMAIL_PASS    = os.environ.get("GMAIL_PASS", "")       # App Password Gmail
ALERT_EMAIL   = os.environ.get("ALERT_EMAIL", "")      # unde trimiți alertele
API_KEY       = os.environ.get("API_KEY", "changeme")  # cheie simplă anti-spam

# ── PERSISTENȚĂ (fișiere JSON în /data) ───────────────────────
DATA_DIR      = "data"
MESSAGES_FILE = os.path.join(DATA_DIR, "messages.json")
FLOODS_FILE   = os.path.join(DATA_DIR, "floods.json")

os.makedirs(DATA_DIR, exist_ok=True)

def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# ── HELPERS ───────────────────────────────────────────────────

def now_ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def send_email_async(subject, body):
    """Trimite email în thread separat ca să nu blocheze request-ul."""
    def _send():
        if not GMAIL_USER or not GMAIL_PASS or not ALERT_EMAIL:
            print("[EMAIL] Credențiale lipsă, emailul nu a fost trimis.")
            return
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"]    = GMAIL_USER
            msg["To"]      = ALERT_EMAIL
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(GMAIL_USER, GMAIL_PASS)
                s.sendmail(GMAIL_USER, ALERT_EMAIL, msg.as_string())
            print(f"[EMAIL] Trimis: {subject}")
        except Exception as e:
            print(f"[EMAIL] Eroare: {e}")
    threading.Thread(target=_send, daemon=True).start()

def check_api_key():
    key = request.headers.get("X-API-Key") or request.args.get("key")
    return key == API_KEY

# ── RUTE ESP (polling de pe ESP) ──────────────────────────────

@app.route("/esp/messages/pending")
def esp_get_pending():
    """
    ESP face GET la această rută periodic.
    Returnează mesajele neprelucrate și le marchează ca livrate.
    """
    if not check_api_key():
        return jsonify({"error": "unauthorized"}), 401

    messages = read_json(MESSAGES_FILE, [])
    pending  = [m for m in messages if not m.get("delivered")]

    for m in messages:
        if not m.get("delivered"):
            m["delivered"] = True

    write_json(MESSAGES_FILE, messages)
    return jsonify({"messages": [m["text"] for m in pending]})


@app.route("/esp/flood", methods=["POST"])
def esp_flood_event():
    """
    ESP trimite POST când detectează inundație.
    Body JSON: {"value": 450}
    """
    if not check_api_key():
        return jsonify({"error": "unauthorized"}), 401

    data   = request.get_json(silent=True) or {}
    value  = data.get("value", "?")
    ts     = now_ts()

    floods = read_json(FLOODS_FILE, [])
    floods.append({"ts": ts, "value": value})
    floods = floods[-10:]   # păstrează ultimele 10
    write_json(FLOODS_FILE, floods)

    send_email_async(
        subject=f"⚠️ FLOOD DETECTED — {ts}",
        body=f"Senzorul de inundație a detectat apă.\n\nValoare ADC: {value}\nTimestamp: {ts}\n\nVerifică sistemul!"
    )

    return jsonify({"status": "ok", "ts": ts})


# ── RUTE BROWSER (UI) ─────────────────────────────────────────

@app.route("/api/messages", methods=["GET"])
def api_get_messages():
    """Returnează toate mesajele (pentru UI)."""
    messages = read_json(MESSAGES_FILE, [])
    return jsonify(messages)


@app.route("/api/messages", methods=["POST"])
def api_send_message():
    """
    Browserul trimite un mesaj nou din Cloud spre ESP.
    Body JSON: {"text": "hello esp"}
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400

    messages = read_json(MESSAGES_FILE, [])
    messages.append({
        "id":        len(messages),
        "text":      text,
        "ts":        now_ts(),
        "delivered": False
    })
    messages = messages[-10:]   # păstrează ultimele 10
    write_json(MESSAGES_FILE, messages)

    return jsonify({"status": "queued", "total": len(messages)})


@app.route("/api/messages/<int:msg_id>", methods=["DELETE"])
def api_delete_message(msg_id):
    """Șterge un mesaj după id."""
    messages = read_json(MESSAGES_FILE, [])
    messages = [m for m in messages if m.get("id") != msg_id]
    write_json(MESSAGES_FILE, messages)
    return jsonify({"status": "deleted"})


@app.route("/api/floods", methods=["GET"])
def api_get_floods():
    """Returnează istoricul de inundații (pentru UI)."""
    floods = read_json(FLOODS_FILE, [])
    return jsonify(floods)


@app.route("/api/floods/<int:idx>", methods=["DELETE"])
def api_delete_flood(idx):
    """Șterge un eveniment de inundație după index."""
    floods = read_json(FLOODS_FILE, [])
    if 0 <= idx < len(floods):
        floods.pop(idx)
        write_json(FLOODS_FILE, floods)
        return jsonify({"status": "deleted"})
    return jsonify({"error": "invalid index"}), 400


@app.route("/api/status")
def api_status():
    """Health check."""
    return jsonify({"status": "online", "ts": now_ts()})


# ── SERVIRE FRONTEND STATIC ───────────────────────────────────

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    if path and os.path.exists(os.path.join("static", path)):
        return send_from_directory("static", path)
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
