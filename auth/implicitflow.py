"""
OAuth 2.0 Implicit Grant Flow Client
=================================================================

This script sets up a minimal Flask server to demonstrate the OAuth 2.0 Implicit Grant flow.
It constructs an authorization URL and prints it to the console. The user is expected to visit
this URL to initiate the login process via the authorization server.

Once authenticated, the user is redirected back to the specified `redirect_uri` with an access token
embedded in the URL fragment (after the `#` symbol). This token can then be used to make authorized
requests to protected resources.

Setup Instructions:
- Replace `app_key` with your actual application key.
- Ensure the `redirect_url` matches the one registered with your OAuth provider.
- Run the server using: `python your_script.py`
- Open the printed authorization URL in a browser to begin the flow.

How It Works:
- Constructs the full authorization URL using:
    - `response_type=token` (required for implicit flow)
    - `client_id` (your app key)
    - `redirect_uri` (where the token will be sent)
- Starts a Flask server on the port specified in the `redirect_uri` (default: 4000)
- The server does not handle the token directly; the token is returned in the browser's address bar
  and must be extracted using client-side JavaScript (or just copied from the URL manually for testing).

Security Notes:
- The Implicit Grant flow is suitable for public clients (e.g., single-page apps) that cannot securely store secrets.
- It does not support refresh tokens, so access tokens must be re-obtained after expiration.
- For server-side apps, consider using the Authorization Code Flow instead.

"""


from flask import Flask, request
import urllib.parse


app_key = ""
redirect_url = urllib.parse.quote("http://localhost:4000/")
authorization_url = "https://sim.logonvalidation.net/authorize"

full_authorization_url = f"{authorization_url}?response_type=token&client_id={app_key}&redirect_uri={redirect_url}"

print(f"\nAuthorization endpoint ({full_authorization_url})")


app = Flask(__name__)



# on port 80 for now
if __name__ == '__main__':
    app.run(port=4000)

    