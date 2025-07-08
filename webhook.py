from flask import Flask, request, jsonify
import os, logging, requests, json

# === Logging Setup ===
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# === Load Environment Variables from Render ===
ACC_ID   = os.environ["CAP_ACCOUNT_ID"]
API_KEY  = os.environ["CAP_API_KEY"]
EMAIL    = os.environ["CAP_EMAIL"]
PW       = os.environ["CAP_PASS"]
DEMO     = os.environ.get("CAP_DEMO", "true").lower() == "true"
EPIC     = os.environ.get("CAP_EPIC", "IX.D.SPTRD.DAILY.IP")  # e.g. US_500

HOST = "https://demo-api-capital.backend-capital.com" if DEMO else "https://api-capital.backend-capital.com"

# === Start Capital Session ===
session = requests.Session()
session.headers.update({"X-CAP-API-KEY": API_KEY})
try:
    res = session.post(
        f"{HOST}/api/v1/session",
        json={"identifier": EMAIL, "password": PW, "encryptedPassword": "false"},
        timeout=10
    )
    res.raise_for_status()
    tokens = res.json()
    cst, xst = tokens["cst"], tokens["securityToken"]
    session.headers.update({"cst": cst, "X-SECURITY-TOKEN": xst})
    logging.info("🔑 Session-Token erhalten")
except requests.HTTPError as e:
    logging.error("❌ Login fehlgeschlagen: %s", res.text)
    exit(1)

# === Position Schließen Funktion ===
def close_position():
    payload = {
        "epic": EPIC,
        "direction": "SELL",  # funktioniert auch für short
        "orderType": "MARKET"
    }
    r = session.post(f"{HOST}/api/v1/positions/close/market", json=payload, timeout=10)
    r.raise_for_status()
    logging.info("🚪 Position geschlossen: %s", r.json().get("dealReference"))

# === Webhook Entry Point ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json() or {}
    logging.info("\n📩 Payload\n%s", json.dumps(data, indent=2))

    action = data.get("action")
    side   = data.get("side")
    size   = float(data.get("contracts", 0))

    if action == "entry":
        if side not in ("long", "short") or size <= 0:
            return jsonify(error="bad_payload"), 400

        order = {
            "direction": "BUY" if side == "long" else "SELL",
            "epic": EPIC,
            "size": size,
            "orderType": "MARKET",
            "forceOpen": True,
            "currencyCode": "USD"
        }

        try:
            r = session.post(f"{HOST}/api/v1/positions/{ACC_ID}", json=order, timeout=10)
            r.raise_for_status()
            deal_id = r.json().get("dealReference")
            logging.info("✅ Order gesendet – Deal: %s", deal_id)
            return jsonify(status="order_sent", deal=deal_id), 200
        except requests.HTTPError as e:
            logging.error("❌ Capital-HTTP-Error: %s", r.text)
            return jsonify(error="api_failure", details=r.text), 500

    elif action in ("tp", "sl", "time_exit"):
        try:
            close_position()
            return jsonify(status="closed"), 200
        except requests.HTTPError as e:
            logging.error("❌ Close-Error: %s", e.response.text)
            return jsonify(error="close_failed", details=e.response.text), 500

    return jsonify(status="ignored"), 200

# === Run App ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
