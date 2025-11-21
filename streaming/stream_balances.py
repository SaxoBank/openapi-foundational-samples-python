#!/usr/bin/env python3
"""
Saxo OpenAPI balance streaming with WebSocket binary protocol.

Token Management:
- Supports OAuth Code and PKCE flows (set GRANT_TYPE env var)
- Auto token refresh and WebSocket reauth using refresh token
- Imports retry logic from auth modules (3 retries, 85% refresh interval)

Subscription Management:
- Auto resubscription using ReplaceReferenceId for seamless transitions
- Unique reference IDs with timestamps to prevent reuse
- Proper subscription deletion on resubscription events
"""

import os
import sys
import time
import json
import threading
import requests
import logging
import secrets
import string
from datetime import datetime
from dotenv import load_dotenv
# Load environment and setup logging
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import logging_utils
logging_utils.setup_logging()

# Get OAuth flow type once and reuse throughout the module
FLOW_TYPE = os.getenv("GRANT_TYPE")
if FLOW_TYPE:
    FLOW_TYPE = FLOW_TYPE.lower()
else:
    FLOW_TYPE = None  # Will trigger manual auth if no GRANT_TYPE is set

# Target fields for balance streaming - used in multiple places
TARGET_BALANCE_FIELDS = ["TotalValue", "CollateralAvailable", "MarginAvailableForTrading"]

def format_balance_data(data):
    """Extract target balance fields and add currency."""
    filtered_data = {field: data[field] for field in TARGET_BALANCE_FIELDS if field in data}
    
    if filtered_data and account_currency:
        filtered_data["Currency"] = account_currency
    
    return filtered_data

def check_oauth_config():
    """Check if required OAuth environment variables are configured."""
    # If no GRANT_TYPE is set, OAuth is not configured
    if not FLOW_TYPE:
        return False
    
    app_key = os.getenv("APP_KEY")
    redirect_urls = os.getenv("REDIRECT_URLS")
    auth_endpoint = os.getenv("AUTHORIZATION_ENDPOINT")
    token_endpoint = os.getenv("TOKEN_ENDPOINT")
    
    # Basic OAuth requirements
    if not all([app_key, redirect_urls, auth_endpoint, token_endpoint]):
        return False
    
    # Check flow-specific requirements (secret only required for code flow, not PKCE)
    if FLOW_TYPE == "code":
        app_secret = os.getenv("APP_SECRET")
        return bool(app_secret)
    
    return True  

# Only import authentication modules based on environment configuration
auth_code_flow = None
auth_pkce_flow = None
refresh_token_with_retry = None
calculate_refresh_interval = None
AUTH_AVAILABLE = False

if check_oauth_config():
    try:
        if FLOW_TYPE == "code":
            from auth import auth_code_flow
            from auth.auth_code_flow import refresh_token_with_retry, calculate_refresh_interval
            logging.debug("Imported auth_code_flow module")
            AUTH_AVAILABLE = True
        elif FLOW_TYPE == "pkce":
            from auth import auth_pkce_flow
            from auth.auth_pkce_flow import refresh_token_with_retry, calculate_refresh_interval
            logging.debug("Imported auth_pkce_flow module")
            AUTH_AVAILABLE = True
        else:
            logging.warning(f"Unknown GRANT_TYPE: '{FLOW_TYPE}'. Valid values are 'code' or 'pkce'. Falling back to manual input.")
            AUTH_AVAILABLE = False
        
    except ImportError as e:
        logging.warning(f"Failed to import auth module: {e}. Token refresh functionality disabled.")
        AUTH_AVAILABLE = False
else:
    if FLOW_TYPE is None:
        logging.info("No GRANT_TYPE configured. Manual authentication will be used.")
    else:
        logging.warning("OAuth environment variables not configured. Token refresh functionality disabled.")

try:
    import websocket 
    # Reduce websocket library logging to prevent duplicate messages
    websocket_logger = logging.getLogger('websocket')
    websocket_logger.setLevel(logging.WARNING)
except ImportError:
    logging.critical("Missing websocket-client. Please install.")
    sys.exit(1)

# Configuration and global state
def load_config():
    """Load configuration from environment variables."""
    base_url = os.getenv("OPEN_API_BASE_URL")
    if not base_url:
        raise EnvironmentError("Missing OPEN_API_BASE_URL environment variable")
    
    # Determine streaming URL based on environment
    if "gateway.saxobank.com/sim" in base_url:
        stream_url = "wss://sim-streaming.saxobank.com/sim/oapi/streaming/ws"
        reauth_url = "https://sim-streaming.saxobank.com/sim/oapi/streaming/ws"
    elif "gateway.saxobank.com/openapi" in base_url:
        stream_url = "wss://live-streaming.saxobank.com/openapi/streaming/ws"
        reauth_url = "https://live-streaming.saxobank.com/openapi/streaming/ws"
    else:
        raise EnvironmentError(f"Unrecognized base URL: {base_url}")
    
    return {
        "BASE_URL": base_url,
        "STREAM_URL": stream_url,
        "REAUTH_URL": reauth_url,
        "ACCESS_TOKEN": os.getenv("ACCESS_TOKEN"),
        "CLIENT_KEY": os.getenv("CLIENT_KEY")
    }

config = load_config()
account_currency = None

# JSON logging for stream history
stream_history = {
    "connections": {},  # Grouped by context_id
    "control_messages": []
}
history_lock = threading.Lock()

def log_subscription_event(reference_id, event_type, data, message_id=None, context_id=None):
    """Log subscription events to JSON history."""
    with history_lock:
        # Require context_id for proper tracking
        if not context_id:
            logging.warning(f"No context_id provided for subscription event: {reference_id}")
            return
        
        # Replace with new context - only keep the most recent WebSocket connection
        if context_id not in stream_history["connections"]:
            stream_history["connections"] = {
                context_id: {
                    "created_at": datetime.utcnow().isoformat(),
                    "reference_id_count": 0,
                    "subscriptions": {}
                }
            }
        
        subscriptions = stream_history["connections"][context_id]["subscriptions"]
        
        if reference_id not in subscriptions:
            subscriptions[reference_id] = {
                "created_at": datetime.utcnow().isoformat(),
                "initial_snapshot": None,
                "messages": [],
                "activity_flags": {
                    "has_snapshot": False,
                    "update_count": 0,
                    "last_heartbeat": None
                },
                "status": "active"
            }
            # Update reference_id_count to reflect the number of unique reference IDs
            stream_history["connections"][context_id]["reference_id_count"] = len(subscriptions)
        
        subscription = subscriptions[reference_id]
        timestamp = datetime.utcnow().isoformat()
        
        if event_type == "snapshot":
            subscription["initial_snapshot"] = {
                "timestamp": timestamp,
                "data": data
            }
            subscription["activity_flags"]["has_snapshot"] = True
            
        elif event_type == "update":
            subscription["messages"].append({
                "timestamp": timestamp,
                "data": data,
                "message_id": message_id
            })
            # Keep only the last 50 messages
            if len(subscription["messages"]) > 50:
                subscription["messages"] = subscription["messages"][-50:]
            subscription["activity_flags"]["update_count"] += 1
            
        elif event_type == "heartbeat":
            subscription["activity_flags"]["last_heartbeat"] = timestamp
            
        elif event_type == "deleted":
            subscription["status"] = "deleted"
            subscription["deleted_at"] = timestamp
            # Save history when a subscription is terminated
            save_stream_history()
            
        elif event_type == "replaced":
            subscription["status"] = "replaced"
            subscription["replaced_at"] = timestamp
            if data:
                subscription["replacement_info"] = data
            # Save history when a subscription is replaced
            save_stream_history()

def log_control_message(ref_id, payload, message_id=None, context_id=None):
    """Log control messages to JSON history."""
    with history_lock:
        stream_history["control_messages"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "context_id": context_id,
            "reference_id": ref_id,
            "payload": payload,
            "message_id": message_id
        })
        # Keep only the last 50 control messages
        if len(stream_history["control_messages"]) > 50:
            stream_history["control_messages"] = stream_history["control_messages"][-50:]

def save_stream_history_for_reference(reference_id):
    """Save stream history for a specific reference ID to the main stream_history files."""
    if not reference_id:
        return
    
    try:
        # Just save to the main stream_history files - no reference-specific folders
        save_stream_history()
    except Exception as e:
        logging.error(f"Failed to save stream history for {reference_id}: {e}")

def save_stream_history():
    """Save stream history to JSON files in stream_history directory."""
    try:
        # Create stream_history directory
        logs_dir = "stream_history"
        os.makedirs(logs_dir, exist_ok=True)
        
        with history_lock:
            # Save subscriptions data directly (grouped by context_id)
            subscriptions_file = os.path.join(logs_dir, "subscriptions.json")
            with open(subscriptions_file, "w") as f:
                json.dump(stream_history["connections"], f, indent=2)
            
            # Save control messages directly
            control_file = os.path.join(logs_dir, "control-messages.json")
            with open(control_file, "w") as f:
                json.dump(stream_history["control_messages"], f, indent=2)
    except Exception as e:
        logging.error(f"Failed to save stream history: {e}")

# Helper functions
def generate_reference_id():
    """
    Generate a unique reference ID with 'balance-' prefix.
    
    Uses timestamp + random string to ensure uniqueness across resubscriptions.
    """
    timestamp_suffix = str(int(time.time() * 1000))[-6:]  # Last 6 digits of milliseconds timestamp
    random_string = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    return f"balance-{timestamp_suffix}{random_string}"

def get_client_key(token):
    """Fetch ClientKey from /clients/me endpoint."""
    try:
        response = requests.get(f"{config['BASE_URL']}/port/v1/clients/me", 
                              headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if response.status_code == 200:
            return response.json().get("ClientKey")
        logging.error(f"Failed to get ClientKey: {response.status_code}")
        if response.status_code == 404:
            logging.error("The /port/v1/clients/me endpoint returned 404. Try again.")
        elif response.status_code == 401:
            logging.error("Unauthorized: The access token may be invalid or expired.")
    except Exception as e:
        logging.error(f"ClientKey request failed: {e}")
    return None

def refresh_token_and_reauth_websocket(refresh_token_value, context_id):
    """
    Refresh access token and reauthorize WebSocket (uses retry logic from auth module).
    
    Args:
        refresh_token_value: The refresh token
        context_id: WebSocket context ID for reauth
    
    Returns:
        dict: New token response if successful, None if failed
    """
    if not AUTH_AVAILABLE:
        return None
    
    # Use shared token refresh utility with built-in retry logic
    token_response = refresh_token_with_retry(refresh_token_value)
    
    if token_response:
        new_access_token = token_response.get("access_token")
        if new_access_token:
            # Update the global config
            config["ACCESS_TOKEN"] = new_access_token
            
            # Reauth WebSocket connection
            reauth_success = reauth_websocket_connection(new_access_token, context_id)
            if not reauth_success:
                logging.warning("WebSocket reauth failed - connection may be disconnected when token expires")
                
            return token_response
        else:
            logging.error("No access token in refresh response")
            return None
    
    return None

def reauth_websocket_connection(new_access_token, context_id):
    """
    Reauthorize WebSocket with new access token before current token expires.
    
    Args:
        new_access_token: The new access token
        context_id: WebSocket context ID
    
    Returns:
        bool: True if successful (202 Accepted), False otherwise
    """
    if not context_id:
        logging.error("No context ID provided for WebSocket reauth")
        return False
    
    if not new_access_token:
        return False
    
    try:
        # Construct the reauth URL
        reauth_url = f"{config['REAUTH_URL']}/authorize?contextid={context_id}"
        
        # Send PUT request with new token
        response = requests.put(
            reauth_url,
            headers={"Authorization": f"Bearer {new_access_token}"},
            timeout=15
        )
        
        if response.status_code == 202:
            logging.info("WebSocket reauthorized successfully")
            return True
        else:
            logging.error(f"WebSocket reauth failed with status {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        logging.error(f"WebSocket reauth request failed: {e}")
        return False

class TokenManager:
    """
    Manages automatic token refresh and WebSocket reauthorization.
    """
    
    def __init__(self, refresh_token, context_id, refresh_interval_seconds=300):
        """
        Initialize token manager.
        
        Args:
            refresh_token (str): The refresh token for getting new access tokens
            context_id (str): WebSocket context ID for reauth
            refresh_interval_seconds (int): Seconds between token refreshes. 
                                          Recommended to set as half of token's expires_in value (default: 5 minutes)
        """
        self.refresh_token = refresh_token
        self.context_id = context_id
        self.refresh_interval = refresh_interval_seconds
        self.stop_event = threading.Event()
        self.refresh_thread = None
        
    def start_auto_refresh(self):
        """Start automatic token refresh in background thread."""
        if self.refresh_thread and self.refresh_thread.is_alive():
            return
            
        self.stop_event.clear()
        self.refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self.refresh_thread.start()
        logging.debug(f"Auto-refresh started (interval: {self.refresh_interval}s)")
    
    def stop_auto_refresh(self):
        """Stop automatic token refresh."""
        self.stop_event.set()
        if self.refresh_thread:
            self.refresh_thread.join(timeout=3)
    
    def _refresh_loop(self):
        """Background token refresh loop (retry logic handled by auth module)."""
        while not self.stop_event.wait(self.refresh_interval):
            new_tokens = refresh_token_and_reauth_websocket(
                self.refresh_token, 
                self.context_id
            )
            
            if new_tokens:
                # Update our stored refresh token if a new one was provided
                new_refresh_token = new_tokens.get("refresh_token")
                if new_refresh_token:
                    self.refresh_token = new_refresh_token
                    logging.debug("Refresh token updated")
                
                # Update refresh interval based on new token's expires_in
                new_expires_in = new_tokens.get("expires_in")
                if new_expires_in:
                    new_refresh_interval = calculate_refresh_interval(new_expires_in)
                    if new_refresh_interval != self.refresh_interval:
                        logging.info(f"Updating refresh interval from {self.refresh_interval} to {new_refresh_interval} seconds")
                        self.refresh_interval = new_refresh_interval
                
            else:
                # Retry logic is handled in refresh_token_with_retry()
                logging.error("Token refresh failed. Stopping auto-refresh.")
                break

def authenticate():
    """
    Get access token through OAuth flow or manual input.
    
    Returns:
        tuple: (access_token, refresh_token, expires_in) or (access_token, None, None)
    """
    if not AUTH_AVAILABLE:
        logging.warning("OAuth not configured - requesting manual token input")
        manual_token = input("ACCESS_TOKEN: ").strip()
        config["ACCESS_TOKEN"] = manual_token
        return manual_token, None, None
    
    # OAuth is available and configured - start the flow
    try:
        logging.info(f"Using OAuth {FLOW_TYPE.upper()} flow")
        logging.info("Starting OAuth authentication...")
        
        # Use the auth module that was imported based on environment
        if FLOW_TYPE == "code" and auth_code_flow:
            return run_oauth_flow_interactive(auth_code_flow, "Authorization Code")
        elif FLOW_TYPE == "pkce" and auth_pkce_flow:
            return run_oauth_flow_interactive(auth_pkce_flow, "PKCE")
        else:
            raise Exception(f"Auth module not available for flow type: {FLOW_TYPE}")
            
    except Exception as e:
        logging.warning(f"OAuth flow failed: {e}")
        logging.warning("Falling back to manual ACCESS_TOKEN input")
        manual_token = input("ACCESS_TOKEN: ").strip()
        config["ACCESS_TOKEN"] = manual_token
        return manual_token, None, None


def run_oauth_flow_interactive(auth_module, flow_name):
    """Run the interactive OAuth flow using the specified auth module."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs
    
    # Generate and print the OAuth authorization URL
    if flow_name == "PKCE":
        oauth_auth_url, generated_code_verifier = auth_module.get_auth_url()
    else:
        oauth_auth_url = auth_module.get_auth_url()
        generated_code_verifier = None
    
    logging.log(logging_utils.IMPORTANT_LEVEL_NUM, f"OAuth Authorization URL, click through to log-in: {oauth_auth_url}")
    
    # Global variables for HTTP server
    auth_code = None
    server_error = None
    code_verifier = generated_code_verifier
    
    class AuthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code, server_error, code_verifier
            
            parsed_path = urlparse(self.path)
            
            if parsed_path.path == "/":
                # Redirect to the pre-generated OAuth authorization URL
                self.send_response(302)
                self.send_header("Location", oauth_auth_url)
                self.end_headers()
            elif "code" in parse_qs(parsed_path.query):
                # Handle callback with authorization code
                query = parse_qs(parsed_path.query)
                auth_code = query.get("code", [None])[0]
                
                if auth_code:
                    html = """<!DOCTYPE html>
<html>
<head><title>Authorization Complete</title></head>
<body>
    <h2>Authorization Successful</h2>
    <p>Return to the terminal - streaming will start automatically.</p>
</body>
</html>"""
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(html.encode())
                else:
                    server_error = "No authorization code received"
                    self.send_response(400)
                    self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            pass  # Suppress HTTP server logs
    
    # Parse redirect URL to get port - reuse from environment file
    redirect_url = os.getenv("REDIRECT_URLS")
    parsed = urlparse(redirect_url)
    port = parsed.port if parsed.port else (443 if parsed.scheme == 'https' else 80)
    
    if port in [80, 443]:
        logging.warning(f"Using port {port} - may require root privileges")
    
    # Start HTTP server
    try:
        server = HTTPServer(('', port), AuthHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
    except OSError as e:
        if e.errno == 98:  # Address already in use
            logging.error(f"Port {port} is already in use. Please:")
            logging.error(f"1. Kill any process using port {port}: sudo kill $(lsof -t -i:{port})")
            logging.error(f"2. Or change REDIRECT_URLS in .env to use a different port")
            logging.error(f"3. Or wait for the previous process to terminate")
        raise Exception(f"Could not start HTTP server on port {port}: {e}")
    
    # Wait for authorization code
    logging.info("Waiting for authorization...")
    timeout = 300  # 5 minutes
    start_time = time.time()
    
    while not auth_code and not server_error and (time.time() - start_time) < timeout:
        time.sleep(1)
    
    server.shutdown()
    
    if server_error:
        raise Exception(f"OAuth error: {server_error}")
    elif not auth_code:
        raise Exception(f"Timeout: No authorization received within {timeout} seconds")
    
    # Exchange code for tokens using auth module directly
    if flow_name == "PKCE" and auth_pkce_flow:
        tokens = auth_pkce_flow.exchange_code_for_tokens(auth_code, code_verifier)
    elif flow_name == "Authorization Code" and auth_code_flow:
        tokens = auth_code_flow.exchange_code_for_tokens(auth_code)
    else:
        raise Exception(f"Auth module not available for flow: {flow_name}")
    
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")
    
    if not access_token:
        raise Exception("No access token in response")
    
    # Update global config
    config["ACCESS_TOKEN"] = access_token
    
    logging.log(logging_utils.IMPORTANT_LEVEL_NUM, "Authentication completed successfully!")
    if refresh_token:
        if expires_in:
            logging.info(f"Token expires in {expires_in}s")
    else:
        logging.warning("No refresh token received - automatic token refresh disabled")
    
    return access_token, refresh_token, expires_in


# Ensure we have required tokens
oauth_refresh_token = None
token_expires_in = None
if not config["ACCESS_TOKEN"]:
    config["ACCESS_TOKEN"], oauth_refresh_token, token_expires_in = authenticate()

# Verify we have a valid access token before proceeding
if not config["ACCESS_TOKEN"]:
    logging.error("Failed to obtain access token")
    sys.exit(1)

if not config["CLIENT_KEY"]:
    config["CLIENT_KEY"] = get_client_key(config["ACCESS_TOKEN"])

if not config["CLIENT_KEY"]:
    logging.error("Failed to obtain ClientKey - cannot proceed with streaming")
    sys.exit(1)

def subscribe_balances(context_id, reference_id):
    """Subscribe to balance updates and process the snapshot response."""
    global account_currency
    
    payload = {
        "Arguments": {"ClientKey": config["CLIENT_KEY"]}, 
        "ContextId": context_id, 
        "ReferenceId": reference_id
    }
    try:
        response = requests.post(f"{config['BASE_URL']}/port/v1/balances/subscriptions", 
                               json=payload,
                               headers={"Authorization": f"Bearer {config['ACCESS_TOKEN']}"}, 
                               timeout=15)
        if response.status_code == 201:
            # Process the snapshot from the 201 response
            snapshot_data = response.json().get("Snapshot", {})
            if snapshot_data:
                # Extract currency from original snapshot data
                if account_currency is None:
                    account_currency = snapshot_data.get("Currency", "")
                
                # Log snapshot to JSON history
                log_subscription_event(reference_id, "snapshot", snapshot_data, context_id=context_id)
                
                # Show only the target fields from snapshot
                filtered_snapshot = format_balance_data(snapshot_data)
                
                if filtered_snapshot:
                    logging.info(f"Subscription created (RefID: {reference_id}) - {filtered_snapshot}")
            
            return True
        logging.error(f"Subscription failed: {response.status_code}")
    except Exception as e:
        logging.error(f"Subscription error: {e}")
    return False

def resubscribe_balances(context_id, new_reference_id, old_reference_id):
    """
    Resubscribe to balance updates using ReplaceReferenceId for seamless transition.
    
    This function creates a new subscription with a new reference ID and automatically
    deletes the old subscription using Saxo's ReplaceReferenceId mechanism.
    
    Args:
        context_id (str): WebSocket context ID
        new_reference_id (str): New unique reference ID for the subscription
        old_reference_id (str): Old reference ID to be replaced and deleted
    
    Returns:
        bool: True if resubscription was successful, False otherwise
    """
    payload = {
        "Arguments": {"ClientKey": config["CLIENT_KEY"]}, 
        "ContextId": context_id, 
        "ReferenceId": new_reference_id,
        "ReplaceReferenceId": old_reference_id  # This automatically deletes the old subscription
    }
    try:
        response = requests.post(f"{config['BASE_URL']}/port/v1/balances/subscriptions", 
                               json=payload,
                               headers={"Authorization": f"Bearer {config['ACCESS_TOKEN']}"}, 
                               timeout=15)
        if response.status_code == 201:
            # Process the snapshot from the 201 response
            snapshot_data = response.json().get("Snapshot", {})
            if snapshot_data:
                # Log snapshot for new subscription
                log_subscription_event(new_reference_id, "snapshot", snapshot_data, context_id=context_id)
                
                # Show only the target fields from snapshot
                filtered_snapshot = format_balance_data(snapshot_data)
                
                if filtered_snapshot:
                    logging.info(f"Replaced {old_reference_id} with {new_reference_id} - {filtered_snapshot}")
            
            return True
        else:
            logging.error(f"Resubscription failed: {response.status_code} - {response.text}")
    except Exception as e:
        logging.error(f"Resubscription error: {e}")
    return False

def delete_subscription(reference_id):
    """Delete a subscription by reference ID."""
    try:
        url = f"{config['BASE_URL']}/port/v1/balances/subscriptions/{reference_id}"
        response = requests.delete(url,
                                 headers={"Authorization": f"Bearer {config['ACCESS_TOKEN']}"}, 
                                 timeout=15)
        if response.status_code == 204:
            logging.info(f"Subscription deleted successfully (RefID: {reference_id})")
            # Log deletion to JSON history
            log_subscription_event(reference_id, "deleted", None)
            return True
        else:
            logging.error(f"Failed to delete subscription (RefID: {reference_id}): {response.status_code}")
            return False
    except Exception as e:
        logging.error(f"Subscription deletion error (RefID: {reference_id}): {e}")
        return False

def decode_message(message):
    """Decode binary WebSocket message per Saxo streaming protocol."""
    try:
        if len(message) < 16:
            return None, None, None
        
        idx = 0
        message_id = int.from_bytes(message[idx:idx+8], "little")
        idx += 10
        ref_len = message[idx]
        idx += 1
        ref_id = message[idx:idx+ref_len].decode('ascii')
        idx += ref_len
        payload_format = message[idx]
        idx += 1
        payload_size = int.from_bytes(message[idx:idx+4], "little")
        idx += 4
        
        if payload_format == 0:
            payload = json.loads(message[idx:idx+payload_size].decode('utf-8'))
            return ref_id, payload, message_id
    except Exception:
        pass
    return None, None, None

def handle_message(ref_id, payload, message_id=None, expected_ref_id=None, ws=None):
    """Handle streaming delta messages."""
    if not isinstance(payload, dict):
        return
    
    # Get context_id from websocket if available
    context_id = ws.context_id if ws and hasattr(ws, 'context_id') else None
    
    # Handle control messages
    if ref_id.startswith('_'):
        # Log all control messages
        log_control_message(ref_id, payload, message_id, context_id)
        
        if ref_id == "_disconnect":
            logging.error("WebSocket disconnected by server. You must create a new login session and re-create the websocket and subscriptions.")
            # Save reference-specific files before exit
            if expected_ref_id:
                save_stream_history_for_reference(expected_ref_id)
            if ws:
                ws.close()
            sys.exit(1)  # Exit to force manual restart
        elif ref_id == "_resetsubscriptions":
            if not payload.get("TargetReferenceIds") or (expected_ref_id and expected_ref_id in payload.get("TargetReferenceIds", [])):
                new_reference_id = generate_reference_id()
                
                # Use ReplaceReferenceId flow to seamlessly transition and delete old subscription
                if resubscribe_balances(ws.context_id, new_reference_id, expected_ref_id):
                    # Mark old subscription as replaced in history
                    log_subscription_event(expected_ref_id, "replaced", {"reason": "replaced_by_resubscription", "new_reference_id": new_reference_id}, context_id=context_id)
                    
                    # Update WebSocket to use new reference ID
                    ws.reference_id = new_reference_id
                else:
                    logging.error(f"Resubscription failed for {expected_ref_id}")
                    sys.exit(1)
        elif ref_id == "_heartbeat":
            # Log heartbeat activity
            if expected_ref_id:
                log_subscription_event(expected_ref_id, "heartbeat", payload, message_id, context_id)
                
            if payload.get("Reason") == "SubscriptionPermanentlyDisabled":
                originating_ref_id = payload.get("OriginatingReferenceId")
                if originating_ref_id and originating_ref_id == expected_ref_id:
                    logging.error(f"Subscription permanently disabled (RefID: {originating_ref_id}) - deleting subscription")
                    delete_subscription(originating_ref_id)
                    # Save reference-specific files before exit
                    save_stream_history_for_reference(originating_ref_id)
                    # Exit since subscription is permanently disabled
                    sys.exit(1)
        return
    
    # Handle balance delta messages
    if expected_ref_id and ref_id == expected_ref_id:
        # Extract data (deltas come as "Data" or direct payload)
        data = payload.get("Data", payload)
        
        if isinstance(data, dict):
            # Log balance update to JSON history
            log_subscription_event(ref_id, "update", data, message_id, context_id)
            
            updates = format_balance_data(data)
            
            if updates:
                message_info = f"MsgID: {message_id}, RefID: {ref_id}" if message_id else f"RefID: {ref_id}"
                logging.info(f"Balance update ({message_info}) - {updates}")


# WebSocket event handlers
def on_ws_message(ws, message):
    if isinstance(message, bytes):
        ref_id, payload, message_id = decode_message(message)
        if ref_id:
            handle_message(ref_id, payload, message_id, ws.reference_id, ws)

def on_ws_error(ws, error):
    logging.error(f"WebSocket error: {error}")
    # Mark that we need to resubscribe due to error
    ws.needs_resubscription = True

def on_ws_close(ws, code, msg):
    if code != 1000:
        logging.warning(f"WebSocket closed unexpectedly (code: {code}, message: {msg})")
    # Always mark that we need to resubscribe, regardless of close code
    # This ensures we generate a new reference ID on reconnection
    ws.needs_resubscription = True

def on_ws_open(ws):
    # Check if we need to resubscribe (after reconnection due to error)
    if hasattr(ws, 'old_reference_id') and ws.old_reference_id:
        old_ref_id = ws.old_reference_id
        new_ref_id = ws.reference_id  # Use the new reference ID that was already generated
        
        # Use ReplaceReferenceId flow to seamlessly transition and delete old subscription
        if resubscribe_balances(ws.context_id, new_ref_id, old_ref_id):
            # Mark old subscription as replaced in history
            log_subscription_event(old_ref_id, "replaced", {"reason": "replaced_after_reconnection", "new_reference_id": new_ref_id}, context_id=ws.context_id)
            
            # Clear the old reference ID now that replacement is complete
            ws.old_reference_id = None
            ws.needs_resubscription = False
        else:
            logging.error(f"Failed to replace subscription after reconnection")
            # Keep the old_reference_id to retry on next connection
    else:
        # Initial subscription (not a reconnection)
        if not subscribe_balances(ws.context_id, ws.reference_id):
            logging.error("Failed to subscribe")

def websocket_thread(context_id, reference_id, stop_event):
    """WebSocket connection with auto-reconnection."""
    current_reference_id = reference_id
    old_reference_id = None  # Track previous reference ID for replacement
    
    while not stop_event.is_set():
        url = f"{config['STREAM_URL']}/connect?contextId={context_id}"
        ws = websocket.WebSocketApp(
            url,
            header=[f"Authorization: Bearer {config['ACCESS_TOKEN']}"],
            on_message=on_ws_message,
            on_error=on_ws_error,
            on_close=on_ws_close,
            on_open=on_ws_open
        )
        ws.context_id = context_id
        ws.reference_id = current_reference_id
        ws.needs_resubscription = False
        ws.old_reference_id = old_reference_id
        
        try:
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logging.error(f"Connection error: {e}")
            ws.needs_resubscription = True
        
        # If we need to resubscribe due to error, generate new reference ID
        if not stop_event.is_set() and hasattr(ws, 'needs_resubscription') and ws.needs_resubscription:
            # Save the current reference ID as old (to be replaced)
            old_reference_id = current_reference_id
            
            # Generate a new reference ID for the resubscription
            current_reference_id = generate_reference_id()
            
            time.sleep(5)
        elif not stop_event.is_set():
            time.sleep(5)

def main():
    """Start balance streaming with automatic token management."""
    context_id = f"CTX_{int(time.time())}"
    reference_id = generate_reference_id()
    stop_event = threading.Event()
    
    logging.info(f"Starting balance streaming (Context: {context_id})")
    
    # Initialize token manager if refresh token is available
    token_manager = None
    if oauth_refresh_token and AUTH_AVAILABLE:
        try:
            # Calculate refresh interval as 85% of the token's expires_in time
            refresh_interval = 300  # Default 5 minutes
            refresh_interval = calculate_refresh_interval(token_expires_in)
            if token_expires_in:
                next_refresh_minutes = refresh_interval // 60
                logging.info(f"Token auto-refresh enabled (next refresh in {refresh_interval}s / ~{next_refresh_minutes}m)")
            
            token_manager = TokenManager(oauth_refresh_token, context_id, refresh_interval)
            token_manager.start_auto_refresh()
        except Exception as e:
            logging.warning(f"Could not start token manager: {e}")
    
    logging.log(logging_utils.IMPORTANT_LEVEL_NUM, "Balance streaming started. Press Ctrl+C to stop.")
    
    ws_thread = threading.Thread(target=websocket_thread, args=(context_id, reference_id, stop_event), daemon=True)
    ws_thread.start()
    
    try:
        while ws_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Stopping...")
    finally:
        stop_event.set()
        if token_manager:
            token_manager.stop_auto_refresh()
        ws_thread.join(timeout=3)
        
        # Save stream history before exit
        save_stream_history()

if __name__ == "__main__":
    main()

