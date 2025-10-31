#!/usr/bin/env python3
"""
Saxo OpenAPI balance streaming with WebSocket binary protocol.
Auto-fetches ClientKey and handles control messages.
"""

import os
import sys
import time
import json
import threading
import requests
import logging

# Logging setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.logging_utils import setup_logging
setup_logging()

try:
    import websocket  # websocket-client
except ImportError:
    logging.critical("Missing dependency websocket-client. Install with: pip install websocket-client requests")
    sys.exit(1)

# Configuration
BASE_URL = "https://gateway.saxobank.com/sim/openapi"
STREAM_URL = "wss://sim-streaming.saxobank.com/sim/oapi/streaming/ws" 
REF_ID = "BALANCES"

def get_client_key(token: str):
    """Fetch ClientKey from /clients/me endpoint."""
    try:
        r = requests.get(f"{BASE_URL}/port/v1/clients/me", 
                        headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.status_code == 200:
            client_key = r.json().get("ClientKey")
            if client_key:
                logging.info(f"Retrieved ClientKey: {client_key}")
                return client_key
        logging.error(f"Failed to get ClientKey ({r.status_code}): {r.text[:200]}")
    except Exception as e:
        logging.error(f"ClientKey request failed: {e}")
    return None

# Get tokens
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN") or input("ACCESS_TOKEN: ").strip()
CLIENT_KEY = os.getenv("CLIENT_KEY") or get_client_key(ACCESS_TOKEN)

if not ACCESS_TOKEN or not CLIENT_KEY:
    logging.error("Failed to get required tokens")
    sys.exit(1)

def subscribe_balances(context_id: str):
    """Subscribe to balance updates."""
    payload = {"Arguments": {"ClientKey": CLIENT_KEY}, "ContextId": context_id, "ReferenceId": REF_ID}
    try:
        r = requests.post(f"{BASE_URL}/port/v1/balances/subscriptions", json=payload,
                         headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}, timeout=15)
        if r.status_code == 201:
            logging.important(f"Balance subscription successful (RefId={REF_ID})")
            return True
        logging.error(f"Subscription failed ({r.status_code}): {r.text[:200]}")
    except Exception as e:
        logging.error(f"Subscription error: {e}")
    return False

def decode_message(message: bytes):
    """Decode binary WebSocket message per Saxo streaming protocol."""
    try:
        if len(message) < 16:
            return None, None, None
        idx = 0
        message_id = int.from_bytes(message[idx:idx+8], "little"); idx += 10
        ref_len = message[idx]; idx += 1
        ref_id = message[idx:idx+ref_len].decode('ascii'); idx += ref_len
        payload_format = message[idx]; idx += 1
        payload_size = int.from_bytes(message[idx:idx+4], "little"); idx += 4
        
        if payload_format == 0:
            payload = json.loads(message[idx:idx+payload_size].decode('utf-8'))
            return ref_id, payload, message_id
    except Exception as e:
        logging.debug(f"Decode error: {e}")
    return None, None, None

def handle_message(ref_id: str, payload: dict):
    """Handle streaming messages."""
    if ref_id.startswith('_'):
        if ref_id == "_disconnect":
            logging.warning("Server disconnect message")
        elif ref_id == "_resetsubscriptions":
            if not payload.get("TargetReferenceIds") or REF_ID in payload.get("TargetReferenceIds", []):
                logging.warning("Subscription reset required")
    elif ref_id == REF_ID:
        snap = payload.get("Snapshot", payload)
        if isinstance(snap, dict):
            total = snap.get("TotalValue")
            currency = snap.get("Currency", "")
            if total is not None:
                logging.important(f"BALANCE: {total} {currency}")
            else:
                logging.debug(f"Balance update: {snap}")
    else:
        logging.debug(f"Unknown reference: {ref_id}")


def on_ws_message(ws, message):
    """Handle WebSocket messages."""
    if not isinstance(message, bytes):
        return
    ref_id, payload, _ = decode_message(message)
    if ref_id:
        handle_message(ref_id, payload)

def on_ws_error(ws, error):
    logging.error(f"WebSocket error: {error}")

def on_ws_close(ws, code, msg):
    if code != 1000:
        logging.warning(f"WebSocket closed ({code}: {msg})")

def on_ws_open(ws):
    logging.info("WebSocket connected, subscribing...")
    if not subscribe_balances(ws.context_id):
        logging.error("Subscription failed")

def websocket_thread(context_id: str, stop_event: threading.Event):
    """WebSocket connection with auto-reconnection."""
    while not stop_event.is_set():
        url = f"{STREAM_URL}/connect?contextId={context_id}"
        ws = websocket.WebSocketApp(url, header=[f"Authorization: Bearer {ACCESS_TOKEN}"],
                                   on_message=on_ws_message, on_error=on_ws_error,
                                   on_close=on_ws_close, on_open=on_ws_open)
        ws.context_id = context_id
        
        logging.info(f"Connecting to {url}")
        try:
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logging.error(f"WebSocket error: {e}")
        
        if not stop_event.is_set():
            logging.info("Reconnecting in 5s...")
            time.sleep(5)

def main():
    """Start balance streaming."""
    context_id = f"CTX_{int(time.time())}"
    stop_event = threading.Event()
    
    ws_thread = threading.Thread(target=websocket_thread, args=(context_id, stop_event), daemon=True)
    ws_thread.start()
    
    logging.important("Balance streaming started. Ctrl+C to stop.")
    
    try:
        while ws_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        stop_event.set()
        ws_thread.join(timeout=3)
        logging.info("Stopped.")

if __name__ == "__main__":
    main()

