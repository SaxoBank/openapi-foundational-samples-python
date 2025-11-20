# Saxo OpenAPI Python Authentication & Streaming

Python implementation for Saxo Bank OpenAPI authentication and real-time streaming with automatic
token management.

## Quick Start

### Requirements

- Python 3.7+
- `python-dotenv`
- `requests`
- `websocket-client`
- `.env` configured with own app credentials.

### Available Scripts

- **Authorization Code Flow** → `auth/auth_code_flow.py`
- **Authorization Code with PKCE** → `auth/auth_pkce_flow.py`
- **WebSocket Streaming** → `streaming/stream_balances.py`

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Copy environment file: `cp .env.example .env`
3. Configure `.env` with credentials from
[developer portal](https://www.developer.saxo/openapi/appmanagement)

```bash
APP_NAME=your_app_name_here
APP_KEY=your_app_key_here
AUTHORIZATION_ENDPOINT=https://sim.logonvalidation.net/authorize
TOKEN_ENDPOINT=https://sim.logonvalidation.net/token
GRANT_TYPE=grant-type # "code" or "pkce"
OPEN_API_BASE_URL=https://gateway.saxobank.com/sim/openapi/
REDIRECT_URLS=http://localhost:3000/callback
APP_SECRET=your_app_secret_here # Only for Authorization Code flow
```

## Usage

### Authentication

Run OAuth 2.0 flows to obtain access tokens:

```bash
python3 auth/auth_code_flow.py  # Authorization Code Flow
python3 auth/auth_pkce_flow.py  # Authorization Code with PKCE
```

### Balance Streaming

Automatically detects OAuth configuration and handles authentication to stream real-time balance
updates:

```bash
python3 streaming/stream_balances.py
```

Streams TotalValue, CollateralAvailable, and MarginAvailableForTrading with automatic token refresh
at 85% of token lifetime.

Otherwise defaults to manual token entry, which also disables the refresh flow.

#### How It Works

- **Flow Selection**: From the `.env` `GRANT_TYPE` to `code` or `pkce` - only the required auth
module loads
  - Or use a [24-hour simulation token](https://www.developer.saxo/openapi/token). The streaming
script
will prompt you for it if you have not setup the `.env` file.
- **Token Refresh**: Automatic refresh at 85% of token lifetime with 3-retry mechanism
- **WebSocket Reauth**: Seamless reauthorization on token refresh
- **Connection Recovery**: Auto-reconnection with subscription replacement

#### Stream History

Logs all activity to `stream_history/`:

- `subscriptions.json` - Most recent WebSocket connection with all subscriptions (replaced on new
connection)
- `control-messages.json` - System control messages (last 50)

Each subscription tracks: snapshot, last 50 messages, status (`active`, `replaced`, `deleted`).

## App Registration

Register apps at: <https://www.developer.saxo/openapi/appmanagement>

The app variables are what should populate the `.env` file. 
