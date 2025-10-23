"""
Streamlit demo: Live candlestick chart from Saxo OpenAPI streaming

What this app does
- Connects to Saxo’s streaming WebSocket using a Bearer access token.
- Subscribes to InfoPrices for a small set of UICs (21, 22, 23, 21700189).
- Aggregates ticks into 5-second OHLC bars and renders a live candlestick chart.
- Lets you connect/disconnect from the stream via the sidebar.

Prerequisites
- Python 3.10+
- Packages: streamlit, pandas, plotly, websocket-client, requests
  Install with: pip install -r requirements.txt
- A valid LIVE access token (obtain it via the auth samples in auth/).

How to run
1) From the project root, start Streamlit:
   streamlit run basics/stream_pricedata.py
2) In the sidebar:
   - Paste your LIVE token.
   - Click Connect.
   - Pick a UIC to chart.
3) Click Disconnect to stop the stream.

Notes
- Data is bucketed into 5-second OHLC bars; adjust resample interval in convert_to_ohlc().
- Context/Reference IDs are generated per session.
- If you see no candles, check the terminal for subscription errors or token expiry.
- To change instruments, edit the Uics list in on_open().
"""





import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.graph_objects as go
import threading
import json
import websocket
import secrets
import time
from datetime import datetime
from collections import defaultdict
import requests

# Optional: widen the central container beyond Streamlit's default
st.markdown(
    """
    <style>
      .block-container {max-width: 1600px;}
    </style>
    """,
    unsafe_allow_html=True,
)


# Session state init
if "connected" not in st.session_state:
    st.session_state.connected = False
if "ws_thread" not in st.session_state:
    st.session_state.ws_thread = None
if "ws" not in st.session_state:
    st.session_state.ws = None
if "CONTEXT_ID" not in st.session_state:
    st.session_state.CONTEXT_ID = secrets.token_urlsafe(10)
if "REF_ID" not in st.session_state:
    st.session_state.REF_ID = secrets.token_urlsafe(5)
# Persist market data across reruns (shared with thread) + lock
if "quote_data" not in st.session_state:
    st.session_state.quote_data = defaultdict(list)
if "qd_lock" not in st.session_state:
    st.session_state.qd_lock = threading.Lock()

CONTEXT_ID = st.session_state.CONTEXT_ID
REF_ID = st.session_state.REF_ID
quote_data = st.session_state.quote_data


# Build a message handler that DOES NOT touch st directly
def make_on_message(quote_store, lock):
    def _on_message(ws, message):
        index = 0
        try:
            msg_id = int.from_bytes(message[index:index + 8], byteorder="little")
            print("MSG ID: " , msg_id)
            index += 8 + 2  # skip version
            ref_id_length = message[index]
            index += 1
            ref_id = message[index:index + ref_id_length].decode()
            index += ref_id_length
            payload_format = message[index]
            index += 1
            payload_size = int.from_bytes(message[index:index + 4], byteorder="little")
            index += 4
            payload = message[index:index + payload_size].decode()
            quotes = json.loads(payload)
            print("Received quotes:", quotes)
            for quote in quotes:
                uic = quote.get("Uic")
                q = quote.get("Quote", {})
                mid = q.get("Mid")
                last_updated = quote.get("LastUpdated")
                if uic and mid and last_updated:
                    try:
                        ts = datetime.strptime(last_updated, "%Y-%m-%dT%H:%M:%S.%fZ")
                        with lock:
                            quote_store[uic].append({"timestamp": ts, "mid": mid})
                    except ValueError:
                        pass
        except Exception as e:
            print(f"Error processing WebSocket message: {e}")
    return _on_message

def on_error(ws, error):
    print(f"WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("WebSocket closed")

def on_open(ws, token):
    print("WebSocket opened, subscribing...")
    response = requests.post(
        "https://gateway.saxobank.com/openapi/trade/v1/infoprices/subscriptions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "Arguments": {"AssetType": "FxSpot", "Uics": "1957254,21,22,23,21700189"},
            "ContextId": CONTEXT_ID,
            "ReferenceId": REF_ID,
        },
        timeout=10,
    )
    if response.status_code == 201:
        print("Subscription successful")
    else:
        print("Subscription failed:", response.text)

def start_websocket(token, quote_store, lock):
    ws = websocket.WebSocketApp(
        f"wss://live-streaming.saxobank.com/oapi/streaming/ws/connect?ContextId={CONTEXT_ID}",
        header=[f"Authorization: Bearer {token}"],
        on_message=make_on_message(quote_store, lock),
        on_error=on_error,
        on_close=on_close,
        on_open=lambda ws: on_open(ws, token),
    )
    st.session_state.ws = ws
    
    ws.run_forever()
    print("connected")

# Sidebar UI for token and connection controls
st.sidebar.header("Connection")
token_input = st.sidebar.text_input("Paste Bearer token", type="password", help="Access token for the streaming API")
col1, col2 = st.sidebar.columns(2)
connect_clicked = col1.button("Connect")
disconnect_clicked = col2.button("Disconnect")

if connect_clicked:
    if not token_input:
        st.sidebar.error("Token is required")
    elif not st.session_state.connected:
        t = threading.Thread(
            target=start_websocket,
            args=(token_input, st.session_state.quote_data, st.session_state.qd_lock),
            daemon=True,
        )
        t.start()
        st.session_state.ws_thread = t
        st.session_state.connected = True

if disconnect_clicked and st.session_state.connected:
    try:
        if st.session_state.ws is not None:
            st.session_state.ws.close()
    except Exception:
        pass
    st.session_state.connected = False
    st.session_state.ws = None
    st.session_state.ws_thread = None

# Remove duplicate page config below (was causing duplicates)
# st.set_page_config(page_title="Live Candlestick Chart", layout="wide")
# st.title(" Live Candlestick Chart from Saxo Bank WebSocket")

if not st.session_state.connected:
    st.info("Enter your token and click Connect to start streaming.")
    st.stop()

# Stable key to avoid duplicate element IDs
selected_uic = st.selectbox("Select UIC", [1957254, 21, 22, 23, 21700189], key="uic_select")
placeholder = st.empty()

def convert_to_ohlc(data):
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["mid"] = pd.to_numeric(df["mid"], errors="coerce")
    df.dropna(subset=["mid"], inplace=True)
    df.set_index("timestamp", inplace=True)
    ohlc = df["mid"].resample("5s").ohlc()
    return ohlc

# Auto-rerun the script every 1s instead of looping 500 times
st_autorefresh(interval=1000, key="live_refresh")  # milliseconds

# Build and render a single chart per run
with st.session_state.qd_lock:
    data = list(quote_data[selected_uic])

ohlc_data = convert_to_ohlc(data)
if not ohlc_data.empty:
    fig = go.Figure(data=[go.Candlestick(
        x=ohlc_data.index,
        open=ohlc_data["open"],
        high=ohlc_data["high"],
        low=ohlc_data["low"],
        close=ohlc_data["close"],
    )])
    fig.update_layout(
        title=f"UIC {selected_uic} Candlestick Chart",
        xaxis_title="Time",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
    )
    placeholder.plotly_chart(fig, use_container_width=True)
else:
    placeholder.info("Waiting for data...")

    