# ─── webhook.py  – Capital-Connector  ─────────────────────────────────────────
# 1. Nimmt TradingView-Webhook als JSON entgegen
# 2. Erstellt (falls nötig) eine Session und holt X-CAP-API-TOKEN
# 3. Leitet „entry“-Aufträge als Market-Orders an Capital.com (Demo/Live) weiter
# ------------------------------------------------------------------------------

from flask import Flask, request, jsonify
import os, json, logging, requests

# ── Basis-Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
app = Flask(__name__)

# ── Secrets aus Render-Environment ───────────────────────────────────────────
CAP_API_KEY   = os.getenv("CAP_API_KEY")        # API-Key
CAP_ACCOUNT   = os.getenv("CAP_ACCOUNT_ID")     # Konto-ID (numerisch)
CAP_EMAIL     = os.getenv("CAP_EMAIL")          # E-Mail (für Session)
CAP_PASS      = os.getenv("CAP_PASS")           # Passwort
CAP_DEMO      = os.getenv("CAP_DEMO", "true")   # "true" Demo / "false" Live
CAP_EPIC      = os.getenv("CAP_EPIC", "US_500") # Symbol (CFD S&P-500)

BASE_URL = (
    "https://demo-api-capital.backend-capital.com"
    if CAP_DEMO.lower() == "true"
    else "https://api-capital.backend-capital.com"
)

session_token: str | None = None  # globales Session-Token

# ── Funktion: Session holen ──────────────────────────────────────────────────
def create_session() -> None:
    """Erstellt Capital-Session und speichert globales session_token."""
    global session_token
    payload = {"identifier": CAP_EMAIL, "password": CAP_PASS}
    r = requests.post(
        f"{BASE_URL}/api/v1/session",
        headers={
            "X-CAP-API-KEY": CAP_API_KEY,
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=10
    )
    r.raise_for_status()
    session_token = r.json()["token"]
    logging.info("🔑 Neues Session-Token erhalten")

# ── Funktion: Market-Order senden ────────────────────────────────────────────
def place_market(side: str, qty: float) -> None:
    """Sendet BUY/SELL-Order an Capital.  side = 'long' | 'short'."""
    global session_token
    if session_token is None:
        create_session()

    headers = {
        "X-CAP-API-KEY":   CAP_API_KEY,
        "X-CAP-API-TOKEN": session_token,
        "Content-Type":    "application/json"
    }

    payload = {
        "epic"      : CAP_EPIC,
        "direction" : "BUY" if side == "long" else "SELL",
        "size"      : qty,
        "orderType" : "MARKET",
        "timeInForce": "FILL_OR_KILL",
        "forceOpen" : True
    }

    r = requests.post(
        f"{BASE_URL}/api/v1/positions",
        headers=headers,
        json=payload,
        timeout=10
    )

    # Token kann abgelaufen sein – 401 ⇒ neue Session anlegen & Retry
    if r.status_code == 401:
        logging.warning("🔄 Token abgelaufen – erstelle neues")
        create_session()
        headers["X-CAP-API-TOKEN"] = session_token
        r = requests.post(
            f"{BASE_URL}/api/v1/positions",
            headers=headers,
            json=payload,
            timeout=10
        )

    r.raise_for_status()
    logging.info("✅ Order OK – Deal-ID %s", r.json().get("dealId"))

# ── Flask-Routes ─────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    logging.info("📩 Payload\n%s", json.dumps(data, indent=2))

    # nur 'entry' verarbeiten
    if data.get("action") != "entry":
        return jsonify(status="ignored"), 200

    side      = data.get("side")        # long / short
    contracts = data.get("contracts")   # float

    # Grundvalidierung
    if side not in ("long", "short") or not isinstance(contracts, (int, float)):
        return jsonify(error="invalid payload"), 400

    try:
        place_market(side, float(contracts))
        return jsonify(status="order_sent"), 200
    except requests.HTTPError as http_err:
        logging.error("❌ Capital-HTTP-Error: %s", http_err.response.text)
        return jsonify(error=http_err.response.text), 500
    except Exception as e:
        logging.error("❌ Allgemeiner Fehler: %s", str(e))
        return jsonify(error=str(e)), 500

# ── Starten (Render liest Procfile – Zeile wird lokal benötigt) ──────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
