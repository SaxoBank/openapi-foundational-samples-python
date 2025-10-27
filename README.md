
# OpenAPI Python Samples

This repository provides **concise Python examples** for implementing secure authentication and
basic API interactions like placing a trade, searching a client up and more. The samples are
designed to be easy to follow and include structured, color-coded logging to aid in debugging and
development.
To try these samples yourself, download/clone this repo and run the scripts after installing the
requirements.


## Features

- **OAuth 2.0 Authorization Code Flow**  
  → `auth/auth_sample.py`

- **OAuth 2.0 Authorization Code Flow with PKCE**  
  → `auth/auth_sample_PKCE.py`

- **Basics, Including Streaming Prices Example**  
  → `basics/...`


## Requirements

- Python **3.10 or higher** (recommended)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Edit the `.env` file and provide the required values:

   ```env
    APP_NAME=your_app_name_here
    
    APP_KEY=your_app_key_here
    
    AUTHORIZATION_ENDPOINT=https://sim.logonvalidation.net/authorize
    
    TOKEN_ENDPOINT=https://sim.logonvalidation.net/token
    
    GRANT_TYPE=Code
    
    OPEN_API_BASE_URL=https://gateway.saxobank.com/sim/openapi/
    
    REDIRECT_URLS=http://localhost:3000/callback
    
    APP_SECRET=your_app_secret_here
   ```

> **Note:** Ensure that the `RedirectUrl` matches the redirect URI configured in your application on the developer portal. Also make sure that the environment specified in the endpoints and base URL variables is correct to the app you are using. 



## Running the Samples

Before executing the samples, you must register an application on the Saxo developer portal:

**Developer Portal App Management:**  
https://www.developer.saxo/openapi/appmanagement

### Application Setup

Configure your application with the appropriate **OAuth 2.0 grant type** based on the sample you
intend to run:

| Sample File              | Required Grant Type             |
|--------------------------|----------------------------------|
| `auth_sample.py`         | Authorization Code              |
| `auth_sample_PKCE.py`    | Authorization Code with PKCE    |

Ensure that the **redirect URI** specified in the developer portal matches the `RedirectUrl` value
in your `.env` file.
Once your environment is configured and your application is registered on the developer portal, you
can run the samples directly from the command line.


