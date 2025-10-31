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
from dotenv import load_dotenv

# Load environment variables from parent directory
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# Logging setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import logging_utils
logging_utils.setup_logging()

try:
    import websocket  # websocket-client
except ImportError:
    logging.critical("Missing websocket-client. Install with: pip install websocket-client")
    sys.exit(1)

# Load and validate environment variables
def load_config():
    """Load configuration from environment variables."""
    # Load required base URL from environment
    base_url = os.getenv("OPEN_API_BASE_URL")
    if not base_url:
        raise EnvironmentError("Missing required environment variable: OPEN_API_BASE_URL. Please check your .env file.")
    
    config = {
        "BASE_URL": base_url,
        "STREAM_URL": "wss://sim-streaming.saxobank.com/sim/oapi/streaming/ws",  # Streaming-specific URL
        "ACCESS_TOKEN": os.getenv("ACCESS_TOKEN"),
        "CLIENT_KEY": os.getenv("CLIENT_KEY"),
        "REF_ID": "BALANCES"
    }
    
    # Adjust streaming URL based on environment (sim vs live)
    if "gateway.saxobank.com/sim" in base_url:
        config["STREAM_URL"] = "wss://sim-streaming.saxobank.com/sim/oapi/streaming/ws"
    elif "gateway.saxobank.com/openapi" in base_url:
        config["STREAM_URL"] = "wss://live-streaming.saxobank.com/openapi/streaming/ws"
    
    return config

# Load configuration
config = load_config()

def get_client_key(token: str):
    """Fetch ClientKey from /clients/me endpoint."""
    try:
        r = requests.get(f"{config['BASE_URL']}/port/v1/clients/me", 
                        headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.status_code == 200:
            client_key = r.json().get("ClientKey")
            if client_key:
                return client_key
        logging.error(f"Failed to get ClientKey ({r.status_code})")
    except Exception as e:
        logging.error(f"ClientKey request failed: {e}")
    return None

# Get tokens
if not config["ACCESS_TOKEN"]:
    config["ACCESS_TOKEN"] = input("ACCESS_TOKEN: ").strip()

if not config["CLIENT_KEY"]:
    config["CLIENT_KEY"] = get_client_key(config["ACCESS_TOKEN"])

if not config["ACCESS_TOKEN"] or not config["CLIENT_KEY"]:
    logging.error("Failed to get required tokens")
    sys.exit(1)

def subscribe_balances(context_id: str):
    """Subscribe to balance updates."""
    payload = {"Arguments": {"ClientKey": config["CLIENT_KEY"]}, "ContextId": context_id, "ReferenceId": config["REF_ID"]}
    try:
        r = requests.post(f"{config['BASE_URL']}/port/v1/balances/subscriptions", json=payload,
                         headers={"Authorization": f"Bearer {config['ACCESS_TOKEN']}"}, timeout=15)
        if r.status_code == 201:
            logging.info("Balance subscription successful")
            return True
        logging.error(f"Subscription failed ({r.status_code})")
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
    except Exception:
        pass  # Silently ignore decode errors for invalid messages
    return None, None, None

def handle_message(ref_id: str, payload: dict):
    """Handle streaming messages."""
    if ref_id.startswith('_'):
        if ref_id == "_disconnect":
            logging.warning("Server disconnecting")
        elif ref_id == "_resetsubscriptions":
            if not payload.get("TargetReferenceIds") or config["REF_ID"] in payload.get("TargetReferenceIds", []):
                logging.warning("Resubscription required")
    elif ref_id == config["REF_ID"]:
        snap = payload.get("Snapshot", payload)
        if isinstance(snap, dict):
            total = snap.get("TotalValue")
            currency = snap.get("Currency", "")
            if total is not None:
                logging.log(logging_utils.IMPORTANT_LEVEL_NUM, f"BALANCE: {total} {currency}")


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
        logging.warning(f"WebSocket closed unexpectedly ({code})")

def on_ws_open(ws):
    logging.info("WebSocket connected")
    if not subscribe_balances(ws.context_id):
        logging.error("Failed to subscribe")

def websocket_thread(context_id: str, stop_event: threading.Event):
    """WebSocket connection with auto-reconnection."""
    while not stop_event.is_set():
        url = f"{config['STREAM_URL']}/connect?contextId={context_id}"
        ws = websocket.WebSocketApp(url, header=[f"Authorization: Bearer {config['ACCESS_TOKEN']}"],
                                   on_message=on_ws_message, on_error=on_ws_error,
                                   on_close=on_ws_close, on_open=on_ws_open)
        ws.context_id = context_id
        
        logging.info("Connecting to streaming server...")
        try:
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logging.error(f"Connection error: {e}")
        
        if not stop_event.is_set():
            logging.info("Reconnecting in 5s...")
            time.sleep(5)

def main():
    """Start balance streaming."""
    context_id = f"CTX_{int(time.time())}"
    stop_event = threading.Event()
    
    ws_thread = threading.Thread(target=websocket_thread, args=(context_id, stop_event), daemon=True)
    ws_thread.start()
    
    logging.log(logging_utils.IMPORTANT_LEVEL_NUM, "Balance streaming started. Press Ctrl+C to stop.")
    
    try:
        while ws_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Stopping...")
    finally:
        stop_event.set()
        ws_thread.join(timeout=3)

if __name__ == "__main__":
    main()

