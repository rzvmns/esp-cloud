# ESP8266 Cloud — Deploy pe Render

## Structura proiectului

```
esp-cloud/
├── app.py            ← Flask backend
├── requirements.txt
├── render.yaml       ← config Render
├── firmware.ino      ← cod ESP (înlocuiește originalul)
└── static/
    └── index.html    ← frontend (copiază fișierul tău aici)
```

---

## 1. Pregătire Gmail (App Password)

1. Mergi la **myaccount.google.com → Security → 2-Step Verification** (activează dacă nu e)
2. Caută **"App passwords"** → creează una nouă (nume: "ESP Cloud")
3. Copiază parola de 16 caractere → o pui în `GMAIL_PASS` pe Render

---

## 2. Deploy pe Render

1. Push proiectul pe GitHub (fără `data/` și fără `static/index.html` cu date sensibile)
2. Render Dashboard → **New → Web Service** → conectează repo
3. Setări:
   - **Runtime**: Python
   - **Build**: `pip install -r requirements.txt`
   - **Start**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2`
4. **Environment Variables** (Render Dashboard → Environment):
   ```
   GMAIL_USER   = tine@gmail.com
   GMAIL_PASS   = xxxx xxxx xxxx xxxx   (App Password, fără spații)
   ALERT_EMAIL  = destinatar@gmail.com
   API_KEY      = un-string-secret-ales-de-tine
   ```
5. **Disk** (pentru persistență JSON între restarts):
   - Render Dashboard → **Disks** → Add Disk
   - Mount Path: `/opt/render/project/src/data`
   - Size: 1 GB (free)

---

## 3. Configurare ESP firmware

În `firmware.ino`, modifică:
```cpp
#define CLOUD_HOST    "https://NUMELE-TAU.onrender.com"
#define CLOUD_API_KEY "un-string-secret-ales-de-tine"   // același ca API_KEY
```

Adaugă în Arduino IDE → Library Manager:
- `ArduinoJson` (by Benoit Blanchon)

---

## 4. Copiază frontend-ul

```
cp index.html esp-cloud/static/index.html
```

Render servește fișierele din `static/` automat prin Flask.

---

## API Reference (pentru debug)

| Endpoint | Metodă | Descriere |
|---|---|---|
| `GET /api/status` | — | Health check |
| `GET /api/messages` | — | Toate mesajele |
| `POST /api/messages` | `{"text":"..."}` | Trimite mesaj spre ESP |
| `DELETE /api/messages/<id>` | — | Șterge mesaj |
| `GET /api/floods` | — | Evenimente inundație |
| `DELETE /api/floods/<idx>` | — | Șterge eveniment |
| `GET /esp/messages/pending` | Header: `X-API-Key` | ESP polling |
| `POST /esp/flood` | `{"value":450}` + API Key | ESP raportează flood |

---

## Flow complet

```
Browser (Render URL)
  → POST /api/messages {"text": "aprinde LED"}
      → Flask salvează în data/messages.json (delivered: false)

ESP (la fiecare 15s)
  → GET /esp/messages/pending  [X-API-Key: ...]
      ← ["aprinde LED"]
      → Flask marchează delivered: true
      → ESP salvează în LittleFS /messages.txt + afișează pe Serial

ESP detectează flood
  → POST /esp/flood {"value": 450}  [X-API-Key: ...]
      → Flask salvează în data/floods.json
      → Flask trimite email la ALERT_EMAIL
```
