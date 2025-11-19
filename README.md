# Saxo OpenAPI Python Authentication & Streaming

Python implementation for Saxo Bank OpenAPI authentication and real-time streaming with automatic
token management.

## Requirements

- Python 3.7+
- `python-dotenv`
- `requests`
- `websocket-client`

## Available Scripts

- `auth/auth_code_flow.py` - OAuth Authorization Code flow (server-side apps with client secret)
- `auth/auth_pkce_flow.py` - OAuth PKCE flow (public clients, mobile apps)
- `streaming/stream_balances.py` - Real-time balance streaming with automatic token management

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Configure `.env` file (copy from `.env.example`) with credentials from 
[developer portal](https://www.developer.saxo/openapi/appmanagement)
3. For streaming: Set `ACCESS_TOKEN` or configure `GRANT_TYPE` for OAuth flow

## Usage

### Balance Streaming

Automatically detects OAuth configuration and handles authentication:

```bash
python3 streaming/stream_balances.py
```

Streams TotalValue, CollateralAvailable, and MarginAvailableForTrading with automatic token refresh
at 85% of token lifetime.

### Manual Authentication Testing

Test authentication flows independently:

```bash
python3 auth/auth_code_flow.py  # Server-side apps with client secret
python3 auth/auth_pkce_flow.py  # Public clients, mobile apps
```

## Stream History

Logs all activity to `stream_history/`:

- `subscriptions.json` - Current WebSocket connection with all subscriptions (replaced on new
connection)
- `control-messages.json` - System control messages (last 50)

Each subscription tracks: snapshot, last 50 messages, status (`active`, `replaced`, `deleted`).

## Configuration

### Environment Variables

```bash
# OAuth
APP_KEY=your_app_key
APP_SECRET=your_app_secret  # Only for Authorization Code flow
AUTHORIZATION_ENDPOINT=https://sim.logonvalidation.net/authorize
TOKEN_ENDPOINT=https://sim.logonvalidation.net/token
REDIRECT_URLS=http://localhost:3000/callback
GRANT_TYPE=code  # "code" or "pkce"

# API
OPEN_API_BASE_URL=https://gateway.saxobank.com/sim/openapi/
```

### How It Works

- **Flow Selection**: Set `GRANT_TYPE` to `code` or `pkce` - only the required auth module loads
- **Token Refresh**: Automatic refresh at 85% of token lifetime with 3-retry mechanism
- **WebSocket Reauth**: Seamless reauthorization on token refresh
- **Connection Recovery**: Auto-reconnection with subscription replacement
