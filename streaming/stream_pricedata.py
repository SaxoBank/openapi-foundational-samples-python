#!/usr/bin/env python3
"""
Basic console demo: Stream price quotes + balances from Saxo OpenAPI (SIM)
- Subscribes to InfoPrices and Balances
- Logs raw quotes (no calculations)
- Uses corporate HTTP proxy for REST + WebSocket
"""

import os
import sys
import time
import json
import threading
from datetime import datetime
import requests
import traceback

# Logging setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.logging_utils import setup_logging
setup_logging()
import logging

try:
    import websocket  # websocket-client
except ImportError:
    logging.critical("Missing dependency websocket-client. Install with: pip install websocket-client requests")
    sys.exit(1)

# ---------- Configuration ----------
UIC_LIST = [1957254, 21, 22, 23, 21700189]
ASSET_TYPE = "FxSpot"

SUBSCRIPTION_ENDPOINT = "https://gateway.saxobank.com/sim/openapi/trade/v1/infoprices/subscriptions"
BALANCES_SUBSCRIPTION_ENDPOINT = "https://gateway.saxobank.com/sim/openapi/port/v1/balances/subscriptions"
WS_URL_TEMPLATE = "wss://sim-streaming.saxobank.com/sim/oapi/streaming/ws/connect?ContextId={context_id}"

BALANCES_REF_ID = "BALANCES"
PRICES_REF_ID = "PRICES"

# ---------- Proxy ----------
# Just for saxo internal.....
PROXY_URL = os.getenv("PROXY_URL", "http://usr:pwd@dk.proxy.mid.dom:80")

def parse_proxy(url: str):
    if "://" not in url:
        url = "http://" + url
    scheme, rest = url.split("://", 1)
    auth_part, host_part = rest.split("@", 1) if "@" in rest else ("", rest)
    user = pwd = None
    if auth_part:
        if ":" in auth_part:
            user, pwd = auth_part.split(":", 1)
        else:
            user = auth_part
    host = host_part
    port = 80
    if ":" in host_part:
        host, port_str = host_part.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            pass
    return scheme, host, port, user, pwd

_scheme, proxy_host, proxy_port, proxy_user, proxy_pass = parse_proxy(PROXY_URL)
PROXIES = {"http": PROXY_URL, "https": PROXY_URL}
logging.info(f"Proxy configured: {PROXY_URL}")

# ---------- Token / Client configuration ----------
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
CLIENT_KEY = os.getenv("CLIENT_KEY")
if not ACCESS_TOKEN:
    logging.important("No ACCESS_TOKEN env var set. Paste Bearer access token:")
    try:
        ACCESS_TOKEN = input("> ").strip()
    except EOFError:
        logging.error("No token provided (EOF).")
        sys.exit(1)
if not ACCESS_TOKEN:
    logging.error("Access token is required.")
    sys.exit(1)
if not CLIENT_KEY:
    logging.important("No CLIENT_KEY env var set. Enter ClientKey for balances subscription (or leave blank to skip):")
    try:
        CLIENT_KEY = input("ClientKey> ").strip()
    except EOFError:
        CLIENT_KEY = ""

# ---------- Subscriptions ----------
def subscribe_prices(context_id: str):
    payload = {
        "Arguments": {"AssetType": ASSET_TYPE, "Uics": ",".join(map(str, UIC_LIST))},
        "ContextId": context_id,
        "ReferenceId": PRICES_REF_ID
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    try:
        r = requests.post(
            SUBSCRIPTION_ENDPOINT,
            json=payload,
            headers=headers,
            proxies=PROXIES,
            timeout=15
        )
    except requests.RequestException as e:
        logging.error(f"Price subscription network error: {e}")
        return False
    if r.status_code == 201:
        logging.important(f"Price subscription successful (RefId={PRICES_REF_ID}).")
        return True
    logging.error(f"Price subscription failed ({r.status_code}): {r.text[:300]}")
    return False


def subscribe_balances(context_id: str):
    if not CLIENT_KEY:
        logging.warning("Skipping balances subscription (no CLIENT_KEY).")
        return False
    payload = {
        "Arguments": {"ClientKey": CLIENT_KEY},
        "ContextId": context_id,
        "ReferenceId": BALANCES_REF_ID
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    try:
        r = requests.post(
            BALANCES_SUBSCRIPTION_ENDPOINT,
            json=payload,
            headers=headers,
            proxies=PROXIES,
            timeout=15
        )
    except requests.RequestException as e:
        logging.error(f"Balances subscription network error: {e}")
        return False
    if r.status_code == 201:
        logging.important(f"Balances subscription successful (RefId={BALANCES_REF_ID}).")
        return True
    logging.error(f"Balances subscription failed ({r.status_code}): {r.text}")
    return False

# ---------- Decode ----------
def decode_message(message: bytes):
    try:
        idx = 0
        _msg_id = int.from_bytes(message[idx:idx+8], "little"); idx += 8
        idx += 2  # version
        ref_len = message[idx]; idx += 1
        ref_id = message[idx:idx+ref_len].decode(); idx += ref_len
        _fmt = message[idx]; idx += 1
        payload_size = int.from_bytes(message[idx:idx+4], "little"); idx += 4
        payload_raw = message[idx:idx+payload_size].decode()
        payload = json.loads(payload_raw)
        return ref_id, payload
    except Exception as e:
        logging.warning(f"Failed to decode frame: {e}")
        return None, None

# ---------- Handlers ----------
def log_price_quotes(payload):
    quotes = payload if isinstance(payload, list) else [payload]
    printed = 0
    for q in quotes:
        uic = q.get("Uic")
        quote = q.get("Quote", {})
        mid = quote.get("Mid")
        lu = q.get("LastUpdated")
        if not (uic and mid and lu):
            continue
        try:
            dt = datetime.strptime(lu, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            dt = lu
        logging.info(f"PRICE UIC={uic} Mid={mid} Time={dt}")
        printed += 1
        if printed >= 10:
            break
    
def log_balances(payload):
    snapshot = payload.get("Snapshot") if isinstance(payload, dict) else None
    snap = snapshot or payload
    if not isinstance(snap, dict):
        logging.debug(f"Balances unexpected structure: {type(snap)}")
        return
    total = snap.get("TotalValue")
    logging.important(f"BALANCES TotalValue={total}")

# ---------- WebSocket callbacks ----------
def on_ws_message(ws, message):
    if isinstance(message, str):
        return
    ref_id, payload = decode_message(message)
    if ref_id is None:
        return
    if ref_id == BALANCES_REF_ID:
        log_balances(payload)
        return
    if ref_id == PRICES_REF_ID:
        log_price_quotes(payload)
        return

def on_ws_error(ws, error):
    logging.error(f"WebSocket error: {error}")

def on_ws_close(ws, code, msg):
    logging.warning(f"WebSocket closed (code={code} msg={msg}). Reconnect pending.")

def on_ws_open(ws):
    logging.info("WebSocket opened; subscribing...")
    prices_ok = subscribe_prices(ws.context_id)
    bal_ok = subscribe_balances(ws.context_id)
    if not prices_ok and not bal_ok:
        logging.error("All subscriptions failed.")

# ---------- WebSocket thread ----------
def websocket_thread(context_id: str, stop_event: threading.Event):
    while not stop_event.is_set():
        url = WS_URL_TEMPLATE.format(context_id=context_id)
        ws_app = websocket.WebSocketApp(
            url,
            header=[f"Authorization: Bearer {ACCESS_TOKEN}"],
            on_message=on_ws_message,
            on_error=on_ws_error,
            on_close=on_ws_close,
            on_open=lambda ws: on_ws_open(ws)
        )
        ws_app.context_id = context_id
        logging.info(f"Connecting {url} via proxy {proxy_host}:{proxy_port}")
        try:
            ws_app.run_forever(
                http_proxy_host=proxy_host,
                http_proxy_port=proxy_port,
                http_proxy_auth=(proxy_user, proxy_pass) if proxy_user and proxy_pass else None,
                proxy_type="http",
                ping_interval=30,
                ping_timeout=10,
            )
        except Exception as e:
            logging.error(f"run_forever exception: {e}")
            logging.debug(traceback.format_exc())
        if not stop_event.is_set():
            logging.info("Sleep 5s before reconnect attempt...")
            time.sleep(5)

# ---------- Main ----------
def main():
    context_id = f"CTX_{int(time.time())}"
    stop_event = threading.Event()
    t = threading.Thread(target=websocket_thread, args=(context_id, stop_event), daemon=True)
    t.start()
    logging.important("Streaming started. Ctrl+C to stop.")
    try:
        while t.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutdown requested.")
        stop_event.set()
        time.sleep(2)
    logging.info("Exited cleanly.")

if __name__ == "__main__":
    main()

