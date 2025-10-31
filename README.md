
# OpenAPI Python Samples

Concise Python examples for Saxo OpenAPI authentication and real-time streaming with structured
logging.


## Quick Start

**Requirements:** Python 3.10+ and `pip install -r requirements.txt`

**Available Scripts:**

- **Basic Websocket Streaming Example**  
  → `streaming/stream_balances.py`

## Setup

1. **For Auth Samples:** Configure `.env` file (copy from `.env.example`)
2. **For Streaming:** Set `ACCESS_TOKEN` environment variable or enter when prompted

## Balance Streaming

Stream real-time balance updates via WebSocket:

```bash
export ACCESS_TOKEN="your_bearer_token"
python streaming/stream_balances.py
```

Features: Auto ClientKey retrieval, reconnection, structured logging.

## Developer Portal Setup

Register your application at: <https://www.developer.saxo/openapi/appmanagement>

- `auth_sample.py`: Authorization Code grant
- `auth_sample_PKCE.py`: Authorization Code with PKCE grant

Match redirect URIs between portal and `.env` file.


