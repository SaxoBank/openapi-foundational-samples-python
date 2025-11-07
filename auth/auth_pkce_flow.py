"""
OAuth 2.0 PKCE (Proof Key for Code Exchange) Flow implementation for Saxo OpenAPI.
Use this for public clients (mobile apps, SPAs) that cannot securely store client secrets.
"""

import os
import requests
import hashlib
import base64
import secrets
from urllib.parse import urlencode
from dotenv import load_dotenv
import logging
import sys

# Setup logging
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.logging_utils import setup_logging, raise_critical

setup_logging()


def load_pkce_flow_config():
    """Load configuration for PKCE flow from environment variables."""
    load_dotenv()
    
    required_keys = ["APP_KEY", "TOKEN_ENDPOINT", "REDIRECT_URLS"]
    config = {key: os.getenv(key) for key in required_keys}
    
    missing = [key for key, value in config.items() if not value]
    if missing:
        raise EnvironmentError(
            f"Missing environment variables for PKCE flow: {', '.join(missing)}. "
            "Please check your .env file. Note: APP_SECRET is not required for PKCE flow."
        )
    
    return {
        "APP_KEY": config["APP_KEY"],
        "TOKEN_URL": config["TOKEN_ENDPOINT"],
        "REDIRECT_URL": config["REDIRECT_URLS"]
    }


def generate_pkce_challenge():
    """
    Generate PKCE code verifier and code challenge for OAuth 2.0 PKCE flow.
    
    Returns:
        tuple: (code_verifier, code_challenge) strings
    """
    # Generate code verifier (43-128 characters, URL-safe)
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
    
    # Generate code challenge (SHA256 hash of verifier, base64url encoded)
    challenge_bytes = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')
    
    return code_verifier, code_challenge


def make_pkce_flow_token_request(data, app_key=None, token_url=None):
    """
    Make a token request using PKCE flow (client_id in body, no Basic auth).
    
    Args:
        data (dict): Token request data (grant_type, code/refresh_token, etc.)
        app_key (str, optional): Application key. If not provided, loads from env.
        token_url (str, optional): Token endpoint URL. If not provided, loads from env.
    
    Returns:
        dict: Token response from the server
    
    Raises:
        ConnectionError: If the request fails
        ValueError: If the response is invalid
    """
    if not all([app_key, token_url]):
        config = load_pkce_flow_config()
        app_key = app_key or config["APP_KEY"]
        token_url = token_url or config["TOKEN_URL"]
    
    # Add client_id to request body (no Authorization header for PKCE)
    data["client_id"] = app_key
    
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    try:
        response = requests.post(
            token_url,
            headers=headers,
            data=urlencode(data),
            timeout=15
        )
    except requests.RequestException as e:
        raise ConnectionError(f"Failed to call token endpoint {token_url}: {e}") from e
    
    if not response.ok:
        raise_critical(
            f"Token endpoint {token_url} returned {response.status_code}: {response.text[:500]}"
        )
    
    try:
        return response.json()
    except ValueError as e:
        raise_critical(
            f"Failed to parse JSON from token endpoint {token_url} "
            f"(status {response.status_code}): {e}; raw content: {response.text[:500]}"
        )


def exchange_code_for_tokens(authorization_code, code_verifier, redirect_url=None, **kwargs):
    """
    Exchange an authorization code for access and refresh tokens using PKCE flow.
    
    Args:
        authorization_code (str): The authorization code from OAuth callback
        code_verifier (str): PKCE code verifier used in authorization request
        redirect_url (str, optional): Redirect URI. If not provided, loads from env.
        **kwargs: Additional arguments passed to make_pkce_flow_token_request
    
    Returns:
        dict: Token response containing access_token, refresh_token, expires_in, etc.
    """
    if not code_verifier:
        raise ValueError("code_verifier is required for PKCE flow")
    
    if not redirect_url:
        config = load_pkce_flow_config()
        redirect_url = config["REDIRECT_URL"]
    
    data = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": redirect_url,
        "code_verifier": code_verifier
    }
    
    logging.info("Exchanging authorization code for tokens using PKCE flow...")
    response = make_pkce_flow_token_request(data, **kwargs)
    logging.info("Successfully obtained tokens from authorization code")
    return response


def refresh_access_token(refresh_token, redirect_url=None, **kwargs):
    """
    Use a refresh token to get new access and refresh tokens using PKCE flow.
    
    Args:
        refresh_token (str): The refresh token
        redirect_url (str, optional): Redirect URI. If not provided, loads from env.
        **kwargs: Additional arguments passed to make_pkce_flow_token_request
    
    Returns:
        dict: Token response containing new access_token, refresh_token, expires_in, etc.
    """
    if not refresh_token:
        raise ValueError("Missing refresh_token. Cannot refresh tokens.")
    
    if not redirect_url:
        config = load_pkce_flow_config()
        redirect_url = config["REDIRECT_URL"]
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "redirect_uri": redirect_url,
    }
    
    logging.info("Refreshing access token using PKCE flow...")
    response = make_pkce_flow_token_request(data, **kwargs)
    logging.info("Successfully refreshed access token")
    return response


def get_auth_url(app_key=None, redirect_url=None, authorization_endpoint=None, code_challenge=None):
    """
    Generate the OAuth authorization URL for PKCE flow.
    
    Args:
        app_key (str, optional): Application key. If not provided, loads from env.
        redirect_url (str, optional): Redirect URI. If not provided, loads from env.
        authorization_endpoint (str, optional): Auth endpoint. If not provided, loads from env.
        code_challenge (str, optional): PKCE code challenge. Auto-generated if not provided.
        OAuth Authorization URL:
    https://live.saxobank.com/sim/openapi/authorize?...
    
    1. Starting local server on port 8080...
    2. Opening browser to http://localhost:8080
    3. You'll be redirected to the OAuth authorization URL above
    4. After authorization, the code will be captured automatically
    Returns:
        tuple: (URL, code_verifier) - Save code_verifier for token exchange!
    """
    load_dotenv()
    
    app_key = app_key or os.getenv("APP_KEY")
    redirect_url = redirect_url or os.getenv("REDIRECT_URLS")
    authorization_endpoint = authorization_endpoint or os.getenv("AUTHORIZATION_ENDPOINT")
    
    if not all([app_key, redirect_url, authorization_endpoint]):
        raise EnvironmentError("Missing required OAuth configuration")
    
    # Generate PKCE challenge if not provided
    code_verifier = None
    if not code_challenge:
        code_verifier, code_challenge = generate_pkce_challenge()
    
    params = {
        "response_type": "code",
        "client_id": app_key,
        "redirect_uri": redirect_url,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256"
    }
    
    url = f"{authorization_endpoint}?{urlencode(params)}"
    return url, code_verifier


def start_pkce_flow():
    """
    Start PKCE flow and return authorization URL and code verifier.
    
    Returns:
        dict: Contains 'url' and 'code_verifier' - save code_verifier for token exchange!
    """
    url, code_verifier = get_auth_url()
    return {"url": url, "code_verifier": code_verifier}


# Convenience functions
def get_tokens_from_code(authorization_code, code_verifier):
    """
    Simplified function to get tokens from authorization code using env config.
    
    Args:
        authorization_code (str): The authorization code
        code_verifier (str): PKCE code verifier
    
    Returns:
        dict: Token response
    """
    return exchange_code_for_tokens(authorization_code, code_verifier)


def renew_tokens(refresh_token):
    """
    Simplified function to renew tokens using env config.
    
    Args:
        refresh_token (str): The refresh token
    
    Returns:
        dict: New token response
    """
    return refresh_access_token(refresh_token)


if __name__ == "__main__":
    """
    Interactive OAuth PKCE Flow with automatic code capture.
    Run: python3 auth_pkce_flow.py
    """
    import webbrowser
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs
    
    print("OAuth 2.0 PKCE Flow (for public clients)")
    print("=" * 45)
    
    # Global variables for HTTP server
    auth_code = None
    server_error = None
    code_verifier = None
    
    class AuthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            global auth_code, server_error
            
            parsed_path = urlparse(self.path)
            
            if parsed_path.path == "/":
                # Redirect to the pre-generated authorization URL
                self.send_response(302)
                self.send_header("Location", auth_url)
                self.end_headers()
            elif "code" in parse_qs(parsed_path.query):
                # Handle callback with authorization code
                query = parse_qs(parsed_path.query)
                auth_code = query.get("code", [None])[0]
                
                if auth_code:
                    html = """<!DOCTYPE html>
<html>
<head>
    <title>Authorization Complete</title>
</head>
<body>
    <h2>Authorization Successful</h2>
    <p>You can close this window and return to the terminal.</p>
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
            # Suppress HTTP server logs
            pass
    
    try:
        # Parse redirect URL to get port
        load_dotenv()
        redirect_url = os.getenv("REDIRECT_URLS")
        if not redirect_url:
            raise EnvironmentError("REDIRECT_URLS not configured in .env file")
        
        parsed = urlparse(redirect_url)
        port = parsed.port if parsed.port else (443 if parsed.scheme == 'https' else 80)
        
        if port in [80, 443]:
            print(f"Warning: Using port {port} may require root privileges")
        
        # Generate and print the OAuth authorization URL
        auth_url, global_code_verifier = get_auth_url()
        print(f"\nOAuth Authorization URL:")
        print(f"\nFollow URL and log in to get tokens")
        print(f"{auth_url}")
        
        # Start HTTP server
        server = HTTPServer(('', port), AuthHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        

        
        # Wait for authorization code
        print(f"\nWaiting for authorization code...")
        timeout = 300  # 5 minutes
        start_time = time.time()
        
        while not auth_code and not server_error and (time.time() - start_time) < timeout:
            time.sleep(1)
        
        server.shutdown()
        
        if server_error:
            print(f"\nError: {server_error}")
            exit(1)
        elif not auth_code:
            print(f"\nTimeout: No authorization code received within {timeout} seconds")
            exit(1)
        
        # Exchange code for tokens
        print(f"\n✓ Authorization code received!")
        print(f"5. Exchanging code for tokens...")
        print(f"   Using code verifier: {global_code_verifier[:20]}...")
        tokens = exchange_code_for_tokens(auth_code, global_code_verifier)
        
        print(f"\n✓ Success! Token response:")
        print(f"   Access Token: {tokens.get('access_token', 'N/A')[:20]}...")
        print(f"   Refresh Token: {tokens.get('refresh_token', 'N/A')[:20]}...")
        print(f"   Expires In: {tokens.get('expires_in', 'N/A')} seconds")
        
        # Start automatic token refresh loop
        refresh_interval_seconds = 300  # 5 minutes
        refresh_token = tokens.get('refresh_token')
        if refresh_token:
            print(f"\n6. Starting automatic token refresh loop (every {refresh_interval_seconds} seconds)...")
            print("   Press Ctrl+C to stop the refresh loop")
            
            current_refresh_token = refresh_token
            refresh_count = 0
            
            try:
                while True:
                    refresh_count += 1
                    print(f"\n   Refresh #{refresh_count} - Waiting {refresh_interval_seconds} seconds...")
                    time.sleep(refresh_interval_seconds)
                    
                    print(f"   Refreshing tokens now...")
                    try:
                        new_tokens = refresh_access_token(current_refresh_token)
                        print(f"   ✓ Token refresh completed!")
                        print(f"   New Access Token: {new_tokens.get('access_token', 'N/A')[:20]}...")
                        
                        # Update refresh token if a new one is provided
                        new_refresh_token = new_tokens.get('refresh_token')
                        if new_refresh_token:
                            current_refresh_token = new_refresh_token
                            print(f"   New Refresh Token: {new_refresh_token[:20]}...")
                        
                        expires_in = new_tokens.get('expires_in', 'N/A')
                        print(f"   Expires In: {expires_in} seconds")
                        
                    except Exception as e:
                        print(f"   ✗ Token refresh failed: {e}")
                        print(f"   Stopping refresh loop due to error")
                        break
                        
            except KeyboardInterrupt:
                print(f"\n   Token refresh loop stopped by user (completed {refresh_count-1} refreshes)")
        else:
            print("\n6. No refresh token received - skipping automatic refresh")
        
    except Exception as e:
        print(f"\nError: {e}")
        exit(1)