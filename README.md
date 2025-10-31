
# OpenAPI Python Samples

Concise Python examples for Saxo OpenAPI authentication and real-time streaming with structured
logging.


## Quick Start

**Requirements:** Python 3.10+ and `pip install -r requirements.txt`

**Available Scripts:**

- **Authorization Code Flow**  
    → `auth/auth_sample.py`
  
- **Authorization Code with PKCE**  
    → `auth/auth_sample_PKCE.py`
  
- **Basic Websocket Streaming Example**  
  → `streaming/stream_balances.py`

## Setup

1. **For Auth Samples:** Configure `.env` file (copy from `.env.example`) with your own application details. See **Developer Portal Setup** notes below. 
2. **For Streaming:** Set `ACCESS_TOKEN` environment variable or enter when prompted


## Authentication Samples

Run OAuth 2.0 authentication flows to obtain access tokens:

**Authorization Code Flow:**

```bash
python auth/auth_sample.py
```

**Authorization Code with PKCE:**

```bash
python auth/auth_sample_PKCE.py
```

Both samples will:

- Open your browser for authentication
- Exchange authorization code for access token
- Display the access token for use in other samples

**Prerequisites:**

- Configure your `.env` file with app credentials from developer portal
- Ensure redirect URI matches your portal configuration

## Balance Streaming

Stream real-time balance updates via WebSocket:

```bash
export ACCESS_TOKEN="your_bearer_token"
python streaming/stream_balances.py
```

Features: Auto ClientKey retrieval, reconnection, structured logging.

This sample will not retrieve your access token for you. You can either adapt the authentication samples for this, or [use a 24 hour simulation token found on the developer portal.](https://www.developer.saxo/openapi/token)

## Developer Portal Setup

Register your application at: <https://www.developer.saxo/openapi/appmanagement>

The application values should be those used in the .env file. Make sure the application type (code or PKCE) matches the sample flow you wish to use. 



