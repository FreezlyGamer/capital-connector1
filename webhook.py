from flask import Flask, request, jsonify
import os, json, logging, requests

# ────────────────────────────
#  Capital‑Connector Webhook
#  TradingView  ➜  Render  ➜  Capital.com
#  · Entry  : opens Market‑Order
#  · TP/SL  : closes position
#  · Time‑Exit: closes position
# ────────────────────────────

logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s: %(message)s")
app = Flask(__name__)

# ── Secrets / Environment ─────────────────────────────────────────────
ACC_ID   = os.environ["CAP_ACCOUNT_ID"]             # 8‑stellige Zahl
API_KEY  = os.environ["CAP_API_KEY"]
EMAIL    = os.environ["CAP_EMAIL"]
PW       = os.environ["CAP_PASS"]
DEMO     = os.environ.get("CAP_DEMO", "true").lower() == "true"
EPIC     = os.environ.get("CAP_EPIC", "IX.D.SPTRD.DAILY.IP")  # vollständiger Epic‑Code

BASE_URL = (
    "https://demo-api-capital.backend-capital.com"
    if DEMO else
    "https://api-capital.backend-capital.com"
)

# ── Session‑Login ────────────────────────────────────────────────────
session = requests.Session()
session.headers.update({"X-CAP-API-KEY": API_KEY, "Content-Type": "application/json"})

def create_session():
    resp = session.post(f"{BASE_URL}/api/v1/session",
                        json={"identifier": EMAIL, "password": PW}, timeout=10)
    resp.raise_for_status()
    token = resp.json()["token"]
    session.headers.update({"X-CAP-API-TOKEN": token})
    logging.info("🔑 Session‑Token erhalten")

create_session()

# ── Order‑Funktionen ─────────────────────────────────────────────────

def place_market(side: str, qty: float):
    """Öffnet Market‑Order long/short mit Stückzahl qty."""
    payload = {
        "epic": EPIC,
        "direction": "BUY" if side == "long" else "SELL",
        "size": qty,
        "orderType": "MARKET",
        "timeInForce": "FILL_OR_KILL",
        "forceOpen": True,
        "currencyCode": "USD"
    }
    r = session.post(f"{BASE_URL}/api/v1/positions", json=payload, timeout=10)
    if r.status_code == 401:  # Token abgelaufen
        logging.warning("🔄 Token erneuern")
        create_session()
        r = session.post(f"{BASE_URL}/api/v1/positions", json=payload, timeout=10)
    r.raise_for_status()
    logging.info("✅ Order OK – Deal %s", r.json().get("dealReference"))


def close_position():
    """Schließt gesamte Position des EPIC."""
    payload = {
        "epic": EPIC,
        "direction": "SELL",  # Capital schließt unabhängig von Richtung die Position
        "orderType": "MARKET"
    }
    r = session.post(f"{BASE_URL}/api/v1/positions/close/market", json=payload, timeout=10)
    r.raise_for_status()
    logging.info("🚪 Position geschlossen – Deal %s", r.json().get("dealReference"))

# ── Flask Endpoints ─────────────────────────────────────────────────
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

    if action == "entry":
        if side not in ("long", "short") or not isinstance(qty, (int, float)) or qty <= 0:
            return jsonify(error="bad_payload"), 400
        try:
            place_market(side, float(qty))
            return jsonify(status="order_sent"), 200
        except requests.HTTPError as e:
            logging.error("❌ Capital‑HTTP‑Error: %s", e.response.text)
            return jsonify(error=e.response.text), 500

    elif action in ("tp", "sl", "time_exit"):
        try:
            close_position()
            return jsonify(status="closed"), 200
        except requests.HTTPError as e:
            logging.error("❌ Close‑Error: %s", e.response.text)
            return jsonify(error=e.response.text), 500

    return jsonify(status="ignored"), 200

# ── Run locally (Render nutzt Procfile) ─────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
