"""
OAuth 2.0 Authorization Code Flow Server
=================================================================


This script sets up a simple HTTP server to facilitate OAuth 2.0 authorization code flow.
It redirects users to an authorization endpoint, receives the authorization code,
exchanges it for access and refresh tokens, and demonstrates token renewal.

Setup Instructions:
- Create a `.env` file in the same directory with the following variables:
    APP_KEY=your_app_key_here
    APP_SECRET=your_app_secret_here
    REDIRECT_URLS=http://localhost:3000/callback
    AUTHORIZATION_ENDPOINT=https://example.com/oauth/authorize
    TOKEN_ENDPOINT=https://example.com/oauth/token

How It Works:
- The server uses the `REDIRECT_URLS` to determine:
    1. The port it should run on (e.g., `3000` from `http://localhost:3000/callback`).
    2. The path it should listen for (e.g., `/callback`)
- If no port is specified in the redirect URL, the server defaults to port `80`.
- There must be only one included to work with this example. 



A demo template is provided as `.env.example` to help you get started quickly.
You can copy it using: `cp .env.example .env` and fill in your credentials.


"""





import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, urlencode
from base64 import b64encode
import requests
from dotenv import load_dotenv
import time
import logging
import sys
import threading  # NEW

# Setup logging and color formatting
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.logging_utils import setup_logging
from utils.logging_utils import raise_critical


setup_logging()


# Load and validate environment variables
def load_config(app=None):
    if app:
        return app

    load_dotenv()

    required_keys = ["APP_KEY", "APP_SECRET", "AUTHORIZATION_ENDPOINT", "TOKEN_ENDPOINT", "REDIRECT_URLS"]
    config = {key: os.getenv(key) for key in required_keys}

    missing = [key for key, value in config.items() if not value]
    if missing:
        raise EnvironmentError(
            f"Missing or invalid environment variables: {', '.join(missing)}. "
            "Please check your .env file or provide a valid app config."
        )

    # Validate and extract port from redirect URL
    parsed = urlparse(config["REDIRECT_URLS"])

    # Ensure path is not root
    if not parsed.path or parsed.path == "/":
        raise ValueError(f"Redirect URL '{config['REDIRECT_URLS']}' must include a non-root path (e.g., /callback).")

    # Determine port: use from URL if present, else default to 80
    port = parsed.port or 80
    config["PORT"] = port

    if not parsed.port:
        logging.info(f"No port specified in redirect URL. Defaulting to port {port}.")
    else:
        logging.info(f"Using port {port} from redirect URL.")

    #Log final configuration
    logging.info(f"Loaded config with redirect URL: {config['REDIRECT_URLS']}")
    logging.info(f"Authorization URL: {config['AUTHORIZATION_ENDPOINT']}")
    logging.info(f"Token URL: {config['TOKEN_ENDPOINT']}")

    return {
        "APP_KEY": config["APP_KEY"],
        "APP_SECRET": config["APP_SECRET"],
        "REDIRECT_URL": config["REDIRECT_URLS"],
        "AUTHORIZATION_URL": config["AUTHORIZATION_ENDPOINT"],
        "TOKEN_URL": config["TOKEN_ENDPOINT"],
        "PORT": config["PORT"],
    }

config = load_config()
# Construct full authorization URL
FULL_AUTH_URL = f"{config['AUTHORIZATION_URL']}?response_type=code&client_id={config['APP_KEY']}&redirect_uri={config['REDIRECT_URL']}"

logging.important(f"Please visit the following URL to authorize the application: {FULL_AUTH_URL}")
unpacked_response = {}

class SafeHTTPServer(HTTPServer):
    def handle_error(self, request, client_address):
        # Override default (which prints raw traceback) to avoid duplicates
        logging.CRITICAL(f"Unhandled exception serving {client_address}")

class OAuthHandler(BaseHTTPRequestHandler):

    # Override the default error handling so that it doesn't print the full traceback repeatedly
    def do_GET(self):
        try:
            self._do_get_impl()
        except Exception as e:
            logging.exception("Request handler crashed")
            # Send minimal error response once
            try:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Internal Server Error")
            except Exception:
                pass


    def _do_get_impl(self):
        global unpacked_response
        global cut_off_time

        cut_off_time = 1000  # seconds before access token expiry to refresh
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == "/":
            self.send_response(302)
            self.send_header("Location", FULL_AUTH_URL)
            self.end_headers()
            return

        elif path == urlparse(config["REDIRECT_URL"]).path:
            logging.info("Requesting tokens...")
            unpacked_response, refresh_token, renew_time, auth_token_expiry = self.get_tokens(parsed_path)

            # --- Immediate HTML response so browser stops loading ---
            html = f"""
            <!doctype html>
            <html lang="en">
              <head>
                <meta charset="utf-8" />
                <title>Authorization Successful</title>
                <style>
                  body {{ font-family: Arial, sans-serif; background:#0d1117; color:#e6edf3; padding:40px; }}
                  .card {{ max-width:640px; margin:auto; background:#161b22; padding:32px; border-radius:12px; box-shadow:0 4px 18px rgba(0,0,0,.4); }}
                  h1 {{ margin-top:0; color:#3fb950; }}
                  code, pre {{ background:#1f242c; padding:4px 8px; border-radius:6px; }}
                  .small {{ font-size:.85rem; opacity:.75; line-height:1.3; }}
                  a.btn {{ display:inline-block; margin-top:18px; background:#238636; color:#fff; text-decoration:none; padding:10px 16px; border-radius:6px; }}
                  a.btn:hover {{ background:#2ea043; }}
                </style>
              </head>
              <body>
                <div class="card">
                  <h1>Authorization Complete</h1>
                  <p>Tokens have been obtained successfully.</p>
                  <p>You can now return to the terminal where you started this sample to view token details and background refresh logs.</p>
                  <p class="small">
                    Received at: {time.strftime('%Y-%m-%d %H:%M:%S')}<br>
                    Next refresh in ~{int(renew_time)} seconds (handled in the background).
                  </p>
                  <p class="small">You may also just close this tab.</p>
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
                pass  # ignore client disconnects

            # --- Log token info & spawn background refresh thread ---
            logging.important(f"Token response: {unpacked_response}")
            logging.info(
                f"Will refresh tokens ~{int(renew_time)}s before expiry "
                f"(access token lifetime {auth_token_expiry}s)."
            )

            threading.Thread(
                target=self.run_refresh_loop,
                args=(refresh_token, renew_time),
                daemon=True
            ).start()
            return
        # ...existing code for other paths...

    def get_tokens(self, parsed_path):
        query = parse_qs(parsed_path.query)
        code = query.get("code", [None])[0]

        if not code:
            raise ValueError("Authorization code not found in callback URL.")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config["REDIRECT_URL"],
        }

        response = self.token_request(data)

        auth_token_expiry = response.get("expires_in")
        refresh_token = response.get("refresh_token")

        renew_time = auth_token_expiry - cut_off_time  # refresh will happen before the token expires

        return response, refresh_token, renew_time, auth_token_expiry


    def renew_tokens(self, refresh_token):

        if not refresh_token:
            raise ValueError("Missing refresh_token. Cannot renew tokens.")

        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": config["REDIRECT_URL"],
        }
        renewed = self.token_request(refresh_data)

        new_refresh_token = renewed["refresh_token"]
        renew_time = renewed["expires_in"] - cut_off_time
    
        return renewed, renew_time, new_refresh_token

    def token_request(self, data):
        basic_token = b64encode(f"{config['APP_KEY']}:{config['APP_SECRET']}".encode()).decode()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_token}",
        }

        try:
            response = requests.post(
            config["TOKEN_URL"],
            headers=headers,
            data=urlencode(data),
            timeout=15
            )
        except requests.RequestException as e:
            raise ConnectionError(f"Failed to call token endpoint {config['TOKEN_URL']}: {e}") from e

        if not response.ok:
            raise_critical(
            f"Token endpoint {config['TOKEN_URL']} returned {response.status_code}: {response.text[:500]}"
            )

        try:
            return response.json()
        except ValueError as e:
            raise_critical(
            f"Failed to parse JSON from token endpoint {config['TOKEN_URL']} (status {response.status_code}): {e}; raw content: {response.text[:500]}"
            )
    # NEW: background refresh loop
    def run_refresh_loop(self, refresh_token, initial_sleep):
        try:
            time.sleep(initial_sleep)
            logging.info("Background: Performing first token refresh...")
            refresh_response, new_renew_time, new_refresh_token = self.renew_tokens(refresh_token=refresh_token)

            if not refresh_response.get("refresh_token"):
                logging.warning("Background: No new refresh token on first refresh. Stopping renewal loop.")
                return
            logging.important(f"Background: First refresh response: {refresh_response}")

            current_refresh_token = new_refresh_token
            sleep_time = new_renew_time
            while True:
                time.sleep(sleep_time)
                logging.info("Background: Renewing tokens again...")
                refresh_response, sleep_time, current_refresh_token = self.renew_tokens(
                    refresh_token=current_refresh_token
                )
                logging.important(f"Background: New refresh response: {refresh_response}")
                if not refresh_response.get("refresh_token"):
                    logging.warning("Background: No new refresh token received. Stopping renewal loop.")
                    break
        except Exception:
            logging.exception("Background token renewal loop crashed.")
# Start the server using the port derived from the redirect URL
def run(server_class=SafeHTTPServer, handler_class=OAuthHandler):  # use SafeHTTPServer
    port = config["PORT"]
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    logging.info(f"Server running on port {port}")
    httpd.serve_forever()

    
if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logging.info("Server stopped by user.")
    except Exception as e:
        logging.error(f"Server encountered an error: {e}")
