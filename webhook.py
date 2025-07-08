from flask import Flask, request, jsonify
import os, json, requests, logging

# ── 1. Grund-Konfiguration ─────────────────────────────────────────────────
CAP_API_KEY   = os.getenv("CAP_API_KEY")       # Render-Secret
CAP_ACCOUNT   = os.getenv("CAP_ACCOUNT_ID")    # Render-Secret
CAP_DEMO      = os.getenv("CAP_DEMO", "true")  # "true" Demo / "false" Live
CAP_EPIC      = os.getenv("CAP_EPIC", "US_500")# handelbarer CFD (S&P-500)

BASE_URL = (
    "https://demo-api-capital.backend-capital.com"
    if CAP_DEMO.lower() == "true" else
    "https://api-capital.backend-capital.com"
)

HEADERS = {
    "X-CAP-API-KEY": CAP_API_KEY,
    "Content-Type":  "application/json"
}

# ── 2. Capital-API-Wrapper (nur Market-Order) ─────────────────────────────
def place_market(side: str, qty: float):
    """
    side  : 'long' → BUY  | 'short' → SELL
    qty   : Stückzahl (float)
    """
    direction = "BUY" if side == "long" else "SELL"
    payload = {
        "epic":        CAP_EPIC,
        "direction":   direction,
        "size":        qty,
        "orderType":   "MARKET",
        "timeInForce": "FILL_OR_KILL",
        "forceOpen":   True
    }
    r = requests.post(
        f"{BASE_URL}/api/v1/positions/{CAP_ACCOUNT}",
        headers=HEADERS,
        json=payload,
        timeout=10
    )
    logging.info("Capital response %s %s", r.status_code, r.text.strip())
    r.raise_for_status()

# ── 3. Flask-App ──────────────────────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    logging.info("📩  Payload  %s", json.dumps(data, indent=2))

    action    = data.get("action")      # 'entry' / 'tp' / 'sl' / 'time_exit'
    side      = data.get("side")        # 'long' / 'short'
    contracts = data.get("contracts")   # float/int

    # – Validierung (nur 'entry' wird ausgeführt) –
    if action != "entry":
        return jsonify(status="ignored", reason="action not entry"), 200
    if side not in ("long", "short") or not isinstance(contracts, (int, float)):
        return jsonify(error="invalid side or contracts"), 400

    try:
        place_market(side, float(contracts))
        return jsonify(status="order_sent"), 200
    except Exception as e:
        logging.error("API-Error %s", e)
        return jsonify(error="api_failure"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
