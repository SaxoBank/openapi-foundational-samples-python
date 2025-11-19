# Saxo OpenAPI Python Authentication & Streaming

Minimal Python implementation for Saxo Bank OpenAPI authentication and real-time streaming with
automatic token management and refresh.

## Features

- OAuth 2.0 Authentication (Code flow and PKCE flow)
- Automatic flow detection based on environment configuration
- WebSocket streaming with token refresh and reauthorization
- Structured logging

**Available Scripts:**

- **Authorization Code Flow** 
    → `auth/auth_code_flow.py`
  
- **PKCE Flow** 
    → `auth/auth_pkce_flow.py`
  
- **Balance Streaming** with automatic token management  
  → `streaming/stream_balances.py`

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Copy the environment example:

```bash
cp .env.example .env
```

3. Configure environment variables in `.env` with your own app details.

   Register your application at: <https://www.developer.saxo/openapi/appmanagement>

   The application values should be those used in the .env file. Make sure the application type
(code or PKCE) matches the flow you wish to use.

## Usage

### Quick Start - Balance Streaming

The main streaming script automatically detects your OAuth configuration and handles authentication
(if set up in the .env file, otherwise manual token input is requested):

```bash
# Set GRANT_TYPE in .env to "code" or "pkce", then run:
python3 streaming/stream_balances.py
```

This will:
- Automatically open your browser for OAuth authentication
- Start streaming balance updates (TotalValue, CollateralAvailable, MarginAvailableForTrading)  
- Refresh tokens every 5 minutes automatically
- Reauthorize the WebSocket connection on token refresh

### Manual Authentication Testing

You can run the authentication flows independently for testing:

```bash
# OAuth Code Flow (for server-side apps with client secret)
python3 auth/auth_code_flow.py

# PKCE Flow (for public clients, mobile apps)
python3 auth/auth_pkce_flow.py
```

Both scripts will:

1. Generate the authorization URL based on your `.env` configuration
2. Automatically open your browser for authentication
3. Exchange the authorization code for tokens
4. Start automatic token refresh loop (every 300 seconds)

## Stream History Logging

The balance streaming script automatically logs all activity to JSON files in `stream_history/`:

- **`subscriptions.json`** - Most recent WebSocket connection with all its subscriptions (replaced on each new connection)
- **`control-messages.json`** - System control messages (disconnects, resets, heartbeats)

Each subscription tracks snapshot, last 50 messages, and status (`active`, `replaced`, or `deleted`). Files save immediately on state changes. All logging is thread-safe and git-ignored.

## Architecture

### Environment Configuration

Configure your `.env` file with the required variables:

```bash
# OAuth Configuration
APP_KEY=your_app_key_here
APP_SECRET=your_app_secret_here  # Only required for Authorization Code flow
AUTHORIZATION_ENDPOINT=https://sim.logonvalidation.net/authorize
TOKEN_ENDPOINT=https://sim.logonvalidation.net/token
REDIRECT_URLS=http://localhost:3000/callback

# Flow Selection
GRANT_TYPE=code  # Use "code" or "pkce"

# API Configuration  
OPEN_API_BASE_URL=https://gateway.saxobank.com/sim/openapi/
```

### Conditional Import System

The streaming script only imports the authentication module it needs:

- **GRANT_TYPE=code** → imports `auth_code_flow` only
- **GRANT_TYPE=pkce** → imports `auth_pkce_flow` only  
- **No GRANT_TYPE** → falls back to manual token input

### Token Management

The system includes:

- Automatic token refresh every 5 minutes
- WebSocket reauthorization on token refresh  
- Connection recovery and error handling
- Structured logging for monitoring
- Smart memory usage with conditional imports
