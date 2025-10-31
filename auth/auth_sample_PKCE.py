"""
OAuth 2.0 Authorization Code Flow with PKCE – Local Server Script
=================================================================

This script sets up a local HTTP server to support the OAuth 2.0 Authorization Code Flow
with Proof Key for Code Exchange (PKCE). It's designed for development and testing purposes,
allowing you to authenticate and retrieve tokens from an OAuth provider using a local redirect URI.

What it does:

- Loads configuration from environment variables:
  APP_KEY, REDIRECT_URLS, AUTHORIZATION_ENDPOINT, and TOKEN_ENDPOINT.
- Parses the redirect URI to extract the port and path.
- Generates a PKCE code verifier and challenge.
- Constructs the authorization URL and starts a local HTTP server.
- Redirects to the authorization endpoint.
- Handles the redirect back with the authorization code.
- Exchanges the code for access and refresh tokens.
- Prints token responses to the console.

How to use it:

1. Set the required environment variables in a `.env` file or your shell.
2. Run the script:
       python3 auth_sample_PKCE.py
3. Open a browser and go to `http://localhost:<PORT>/` to start the flow.

Important:

- Within the application registration, the `REDIRECT_URLS` must include a non-root path (e.g., `http://localhost/test`).
- The redirect URL can have a path specified within the .env file, such as `http://localhost:8000/test`.
- There must be only one included to work with this example. 
- If not specified in the .env file, the default port is set to 80. 
    - Running on port 80 requires root privileges:
        sudo python3 oauth_pkce_server.py


"""


import os
import base64
import hashlib
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, urlencode
import requests
from dotenv import load_dotenv
import sys
import logging
import threading  # ADDED
import time       # ADDED

# Setup logging and color formatting
# Setup logging and color formatting
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.logging_utils import setup_logging
from utils.logging_utils import raise_critical


setup_logging()


# Load environment variables
load_dotenv()

# Required environment variables
required_keys = ["APP_KEY", "REDIRECT_URLS", "AUTHORIZATION_ENDPOINT", "TOKEN_ENDPOINT"]
config = {key: os.getenv(key) for key in required_keys}

# Validate environment variables
missing = [key for key, value in config.items() if not value]
if missing:
    raise EnvironmentError(f"Missing environment variables: {', '.join(missing)}")

# Extract RedirectUrl and port 
parsed = urlparse(config["REDIRECT_URLS"])

#Default port is 80 -- http local host, where the redirect sits on. 
config["PORT"] = parsed.port if parsed.port else 80
config["REDIRECT_PATH"] = parsed.path

logging.info(f"Loaded config with redirect URL: {config['REDIRECT_URLS']}")
logging.info(f"Authorization URL: {config['AUTHORIZATION_ENDPOINT']}")
logging.info(f"Token URL: {config['TOKEN_ENDPOINT']}")

# Generate PKCE code_verifier and code_challenge
def generate_pkce_pair():
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

code_verifier, code_challenge = generate_pkce_pair()
state = secrets.token_urlsafe(16)

# Construct authorization URL
authorization_url = (
    f"{config['AUTHORIZATION_ENDPOINT'].rstrip('/')}?"
    f"response_type=code&client_id={config['APP_KEY']}&redirect_uri={config['REDIRECT_URLS']}"
    f"&state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
)

logging.important(f"Please visit the following URL to authorize the application: {authorization_url}")

# Token endpoint
token_url = f"{config['TOKEN_ENDPOINT'].rstrip('/')}"

# HTTP handler
class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)

        if parsed_path.path == "/":
            logging.info("Redirecting user to authorization URL...")
            self.send_response(302)
            self.send_header("Location", authorization_url)
            self.end_headers()
        elif parsed_path.path == config["REDIRECT_PATH"]:
            query = parse_qs(parsed_path.query)
            code = query.get("code", [None])[0]
          
            if not code:
                logging.warning("Missing authorization code in callback URL.")
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing authorization code.")
                return

            logging.info("Exchanging authorization code for tokens...")
            data = {
                "grant_type": "authorization_code",
                "client_id": config["APP_KEY"],
                "code": code,
                "redirect_uri": config["REDIRECT_URLS"],
                "code_verifier": code_verifier
            }
            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            try:
                response = requests.post(token_url, headers=headers, data=urlencode(data), timeout=15)
                response.raise_for_status()
            except requests.RequestException as e:
                logging.error(f"Failed to call token endpoint: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Token exchange failed.")
                return

            try:
                token_response = response.json()
            except ValueError as e:
                logging.error(f"Failed to parse JSON from token endpoint: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Invalid JSON in token response.")
                return

            logging.important(f"Token response: {token_response}")

            refresh_token = token_response.get("refresh_token")

            # --- NEW: Immediate HTML response (non-blocking refresh) ---
            html = f"""
            <!doctype html>
            <html lang="en">
              <head>
                <meta charset="utf-8" />
                <title>Authorization Complete</title>
                <style>
                  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; background:#0d1117; color:#e6edf3; padding:40px; }}
                  .card {{ max-width:640px; margin:auto; background:#161b22; padding:34px 40px; border-radius:14px; box-shadow:0 4px 18px rgba(0,0,0,.5); }}
                  h1 {{ margin-top:0; color:#3fb950; font-size:1.9rem; }}
                  p {{ line-height:1.4; }}
                  .small {{ font-size:.85rem; opacity:.75; line-height:1.3; }}
                  a.btn {{ display:inline-block; margin-top:20px; background:#238636; color:#fff; text-decoration:none; padding:11px 18px; border-radius:8px; font-weight:600; }}
                  a.btn:hover {{ background:#2ea043; }}
                  code {{ background:#1f242c; padding:2px 6px; border-radius:4px; }}
                </style>
              </head>
              <body>
                <div class="card">
                  <h1>Authorization Successful</h1>
                  <p>Your authorization code was exchanged for tokens.</p>
                  <p>Return to the terminal window where you started this script to view the token details and logs.</p>
                  <p class="small">
                    Time: {time.strftime('%Y-%m-%d %H:%M:%S')}<br>
                    {"A background refresh attempt will run shortly." if refresh_token else "No refresh token was issued for this response."}
                  </p>
                  
                  <p class="small">You may also simply close this tab manually.</p>
                </div>
              </body>
            </html>
            """
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            except Exception:
                pass  # ignore disconnects
            # --- END NEW ---

            # Spawn background refresh (optional)
            if refresh_token:
                threading.Thread(
                    target=self._background_refresh_once,
                    args=(refresh_token,),
                    daemon=True
                ).start()
        else:
            logging.error(f"Invalid path requested: {parsed_path.path}")
            self.send_response(404)
            self.end_headers()

    # NEW: background single refresh attempt (demo)
    def _background_refresh_once(self, refresh_token):
        try:
            # Wait a short interval just to demonstrate async behavior
            time.sleep(5)
            logging.info("Background: attempting one refresh token exchange...")
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            refresh_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": config["APP_KEY"],
                "code_verifier": code_verifier
            }
            try:
                r = requests.post(token_url, headers=headers, data=urlencode(refresh_data), timeout=15)
                r.raise_for_status()
                logging.important(f"Background refresh token response: {r.json()}")
            except requests.RequestException as e:
                logging.warning(f"Background refresh failed: {e}")
        except Exception:
            logging.exception("Background refresh thread crashed.")

# Run server
def run():
    server_address = ('', config["PORT"])
    httpd = HTTPServer(server_address, OAuthHandler)
    logging.info(f"Server running on port {config['PORT']}")
    httpd.serve_forever()

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logging.info("Server stopped by user.")
    except Exception as e:
        logging.error(f"Server encountered an error: {e}")