"""
OAuth 2.0 Authorization Code Flow for Saxo OpenAPI.
For server-side applications that can securely store client secrets.
"""

import os
import requests
from base64 import b64encode
from urllib.parse import urlencode
from dotenv import load_dotenv
import logging
import sys
import time

# Setup logging
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.logging_utils import setup_logging, raise_critical

setup_logging()


def load_code_flow_config():
    """Load Authorization Code flow config from environment."""
    load_dotenv()
    
    required_keys = ["APP_KEY", "APP_SECRET", "TOKEN_ENDPOINT", "REDIRECT_URLS"]
    config = {key: os.getenv(key) for key in required_keys}
    
    missing = [key for key, value in config.items() if not value]
    if missing:
        raise EnvironmentError(
            f"Missing environment variables for Authorization Code flow: {', '.join(missing)}. "
            "Please check your .env file."
        )
    
    return {
        "APP_KEY": config["APP_KEY"],
        "APP_SECRET": config["APP_SECRET"],
        "TOKEN_URL": config["TOKEN_ENDPOINT"],
        "REDIRECT_URL": config["REDIRECT_URLS"]
    }


def make_code_flow_token_request(data, app_key=None, app_secret=None, token_url=None):
    """
    Make token request using Authorization Code flow with Basic auth.
    
    Args:
        data: Token request data (grant_type, code/refresh_token, etc.)
        app_key: Application key (loads from env if not provided)
        app_secret: Application secret (loads from env if not provided)
        token_url: Token endpoint URL (loads from env if not provided)
    
    Returns:
        dict: Token response from server
    """
    if not all([app_key, app_secret, token_url]):
        config = load_code_flow_config()
        app_key = app_key or config["APP_KEY"]
        app_secret = app_secret or config["APP_SECRET"]
        token_url = token_url or config["TOKEN_URL"]
    
    # Use Basic authentication for Code flow
    basic_token = b64encode(f"{app_key}:{app_secret}".encode()).decode()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {basic_token}",
    }
    
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


def exchange_code_for_tokens(authorization_code, redirect_url=None, **kwargs):
    """
    Exchange authorization code for access and refresh tokens.
    
    Args:
        authorization_code: The authorization code from OAuth flow
        redirect_url: Redirect URI (loads from env if not provided)
        **kwargs: Additional arguments for make_code_flow_token_request
    
    Returns:
        dict: Token response with access_token, refresh_token, expires_in, etc.
    """
    if not redirect_url:
        config = load_code_flow_config()
        redirect_url = config["REDIRECT_URL"]
    
    data = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": redirect_url,
    }
    
    response = make_code_flow_token_request(data, **kwargs)
    return response


def refresh_access_token(refresh_token, redirect_url=None, **kwargs):
    """
    Get new tokens using refresh token.
    
    Args:
        refresh_token: The refresh token
        redirect_url: Redirect URI (loads from env if not provided)
        **kwargs: Additional arguments for make_code_flow_token_request
    
    Returns:
        dict: Token response with new access_token, refresh_token, expires_in, etc.
    """
    if not refresh_token:
        raise ValueError("Missing refresh_token. Cannot refresh tokens.")
    
    if not redirect_url:
        config = load_code_flow_config()
        redirect_url = config["REDIRECT_URL"]
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "redirect_uri": redirect_url,
    }
    
    response = make_code_flow_token_request(data, **kwargs)
    return response


def refresh_token_with_retry(refresh_token, max_retries=3, retry_delay=1):
    """
    Refresh OAuth token with retry logic (importable by other modules).
    
    Args:
        refresh_token: The refresh token
        max_retries: Maximum retry attempts (default: 3)
        retry_delay: Seconds between retries (default: 1)
    
    Returns:
        dict: Token response (access_token, refresh_token, expires_in) or None if failed
    """
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            logging.info("Refreshing token...")
            token_data = refresh_access_token(refresh_token)
            logging.info("Token refresh successful")
            return token_data
                    
        except Exception as e:
            retry_count += 1
            logging.error(f"Token refresh error: {e}")
            if retry_count < max_retries:
                time.sleep(retry_delay)
    
    logging.error(f"Max retries ({max_retries}) reached. Token refresh failed.")
    return None


def calculate_refresh_interval(expires_in, default=300, min_interval=30):
    """
    Calculate token refresh interval (importable by other modules).
    Returns 85% of token lifetime.
    
    Args:
        expires_in: Token lifetime in seconds
        default: Default interval if expires_in not provided (default: 300)
        min_interval: Minimum refresh interval (default: 60)
    
    Returns:
        int: Refresh interval in seconds
    """
    if expires_in:
        return max(min_interval, int(expires_in * 0.85))
    return default


def get_auth_url(app_key=None, redirect_url=None, authorization_endpoint=None):
    """
    Generate OAuth authorization URL for Code flow.
    
    Args:
        app_key: Application key (loads from env if not provided)
        redirect_url: Redirect URI (loads from env if not provided)
        authorization_endpoint: Auth endpoint (loads from env if not provided)
    
    Returns:
        str: Authorization URL for user to visit
    """
    load_dotenv()
    
    app_key = app_key or os.getenv("APP_KEY")
    redirect_url = redirect_url or os.getenv("REDIRECT_URLS")
    authorization_endpoint = authorization_endpoint or os.getenv("AUTHORIZATION_ENDPOINT")
    
    if not all([app_key, redirect_url, authorization_endpoint]):
        raise EnvironmentError("Missing required OAuth configuration")
    
    params = {
        "response_type": "code",
        "client_id": app_key,
        "redirect_uri": redirect_url
    }
    
    return f"{authorization_endpoint}?{urlencode(params)}"


# Convenience functions
def get_tokens_from_code(authorization_code):
    """
    Simplified function to get tokens from authorization code using env config.
    
    Args:
        authorization_code (str): The authorization code
    
    Returns:
        dict: Token response
    """
    return exchange_code_for_tokens(authorization_code)


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
    Interactive OAuth Code Flow with automatic code capture.
    Run: python3 auth_code_flow.py
    """
    import webbrowser
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs
    
    print("OAuth 2.0 Authorization Code Flow")
    print("=" * 40)
    
    # Global variables for HTTP server
    auth_code = None
    server_error = None
    
    class AuthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            global auth_code, server_error
            
            parsed_path = urlparse(self.path)
            
            if parsed_path.path == "/":
                # Redirect to authorization URL
                auth_url = get_auth_url()
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
        auth_url = get_auth_url()
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
        tokens = exchange_code_for_tokens(auth_code)
        
        print(f"\n✓ Success! Token response:")
        print(f"   Access Token: {tokens.get('access_token', 'N/A')[:20]}...")
        print(f"   Refresh Token: {tokens.get('refresh_token', 'N/A')[:20]}...")
        expires_in = tokens.get('expires_in', 'N/A')
        print(f"   Expires In: {expires_in} seconds")
        
        # Start automatic token refresh loop
        refresh_token = tokens.get('refresh_token')
        if refresh_token:
            # Calculate refresh interval as 85% of the token's expires_in time
            refresh_interval_seconds = calculate_refresh_interval(expires_in if isinstance(expires_in, int) else None)
            
            if isinstance(expires_in, int):
                print(f"\n6. Starting automatic token refresh loop (every {refresh_interval_seconds} seconds, based on token expiry)...")
            else:
                print(f"\n6. Starting automatic token refresh loop (every {refresh_interval_seconds} seconds, using default interval)...")
            
            print("   Press Ctrl+C to stop the refresh loop")
            
            current_refresh_token = refresh_token
            refresh_count = 0
            
            try:
                while True:
                    refresh_count += 1
                    print(f"\n   Refresh #{refresh_count} - Waiting {refresh_interval_seconds} seconds...")
                    time.sleep(refresh_interval_seconds)
                    
                    print(f"   Refreshing tokens now...")
                    new_tokens = refresh_token_with_retry(current_refresh_token)
                    
                    if new_tokens is None:
                        print(f"   ✗ Token refresh failed after all retries. Stopping refresh loop.")
                        print(f"   Manual re-authentication required.")
                        break
                    
                    print(f"   ✓ Token refresh completed!")
                    print(f"   New Access Token: {new_tokens.get('access_token', 'N/A')[:20]}...")
                    
                    # Update refresh token if a new one is provided
                    new_refresh_token = new_tokens.get('refresh_token')
                    if new_refresh_token:
                        current_refresh_token = new_refresh_token
                        print(f"   New Refresh Token: {new_refresh_token[:20]}...")
                    
                    expires_in = new_tokens.get('expires_in', 'N/A')
                    print(f"   Expires In: {expires_in} seconds")
                    
                    # Update refresh interval based on new token's expires_in
                    if isinstance(expires_in, int):
                        new_refresh_interval = calculate_refresh_interval(expires_in)
                        if new_refresh_interval != refresh_interval_seconds:
                            print(f"   Updating refresh interval from {refresh_interval_seconds} to {new_refresh_interval} seconds")
                            refresh_interval_seconds = new_refresh_interval
                        
            except KeyboardInterrupt:
                print(f"\n   Token refresh loop stopped by user (completed {refresh_count-1} refreshes)")
        else:
            print("\n6. No refresh token received - skipping automatic refresh")
        
    except Exception as e:
        print(f"\nError: {e}")
        exit(1)