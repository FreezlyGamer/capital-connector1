from flask import Flask, request, jsonify
import os, json, logging, requests, sys

"""
Capital‑Connector Webhook (v1.2)
• TradingView JSON → Render → Capital.com
• Supports: entry, tp, sl, time_exit
• Robust gegen fehlende ENV‑Variablen & Session‑Timeouts
"""

# ─────────────────── Logging ───────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
app = Flask(__name__)

# ─────────────────── ENV ‑ Variablen ───────────────────
REQUIRED_VARS = [
    "CAP_API_KEY",
    "CAP_EMAIL",
    "CAP_PASS"
]  # CAP_ACCOUNT_ID ist optional – nicht nötig für Orders
missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
if missing:
    logging.critical("❌ Fehlende Environment‑Variablen: %s", ", ".join(missing))
    sys.exit(1)

ACC_ID  = os.getenv("CAP_ACCOUNT_ID")
API_KEY = os.getenv("CAP_API_KEY")
EMAIL   = os.getenv("CAP_EMAIL")
PW      = os.getenv("CAP_PASS")
DEMO    = os.getenv("CAP_DEMO", "true").lower() == "true"
EPIC    = os.getenv("CAP_EPIC", "IX.D.SPTRD.DAILY.IP")

BASE_URL = "https://demo-api-capital.backend-capital.com" if DEMO else "https://api-capital.backend-capital.com"

# ─────────────────── Session Mgmt ───────────────────
session = requests.Session()
session.headers.update({"X-CAP-API-KEY": API_KEY, "Content-Type": "application/json"})

def create_session() -> None:
    """Erstellt/erneuert Session‑Token."""
    resp = session.post(
        f"{BASE_URL}/api/v1/session",
        json={"identifier": EMAIL, "password": PW, "encryptedPassword": "false"},
        timeout=10,
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        logging.critical("❌ Login‑Fehler: %s", resp.text)
        sys.exit(1)
    token = resp.json().get("token")
    if not token:
        logging.critical("❌ Kein token‑Feld in Session‑Antwort: %s", resp.text)
        sys.exit(1)
    session.headers.update({"X-CAP-API-TOKEN": token})
    logging.info("🔑 Session‑Token aktualisiert")

create_session()

# ─────────────────── Order‑Helfer ───────────────────

def _api_post(endpoint: str, payload: dict):
    """Wrapper mit Token‑Retry."""
    r = session.post(f"{BASE_URL}{endpoint}", json=payload, timeout=10)
    if r.status_code == 401:
        logging.warning("🔄 Token abgelaufen – erneuere …")
        create_session()
        r = session.post(f"{BASE_URL}{endpoint}", json=payload, timeout=10)
    r.raise_for_status()
    return r


def place_market(side: str, qty: float):
    payload = {
        "epic": EPIC,
        "direction": "BUY" if side == "long" else "SELL",
        "size": qty,
        "orderType": "MARKET",
        "timeInForce": "FILL_OR_KILL",
        "forceOpen": True,
        "currencyCode": "USD",
    }
    r = _api_post("/api/v1/positions", payload)
    logging.info("✅ Order OK – Deal %s", r.json().get("dealReference"))


def close_position():
    payload = {
        "epic": EPIC,
        "direction": "SELL",  # API schließt long/short auto
        "orderType": "MARKET",
    }
    r = _api_post("/api/v1/positions/close/market", payload)
    logging.info("🚪 Position geschlossen – Deal %s", r.json().get("dealReference"))

# ─────────────────── Flask Routes ───────────────────
@app.route("/health")
def health():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    logging.info("📩 Payload\n%s", json.dumps(data, indent=2))

    action = data.get("action")
    side   = data.get("side")
    qty    = data.get("contracts")

    try:
        if action == "entry":
            if side not in ("long", "short") or not isinstance(qty, (int, float)) or qty <= 0:
                return jsonify(error="bad_payload"), 400
            place_market(side, float(qty))
            return jsonify(status="order_sent"), 200

        elif action in ("tp", "sl", "time_exit"):
            close_position()
            return jsonify(status="closed"), 200

        return jsonify(status="ignored"), 200

    except requests.HTTPError as e:
        logging.error("❌ Capital‑HTTP‑Error: %s", e.response.text)
        return jsonify(error=e.response.text), 500
    except Exception as e:
        logging.error("❌ Allgemeiner Fehler: %s", str(e))
        return jsonify(error=str(e)), 500

# ─────────────────── Run Local ───────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
