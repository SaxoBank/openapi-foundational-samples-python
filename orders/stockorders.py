import requests

# Replace with your actual access token and account key
access_token = ""
account_key = ""


# API endpoint
url = "https://gateway.saxobank.com/sim/openapi/trade/v2/orders"

# Headers
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}

# Order payload for a LIMIT order
payload = {
    "AccountKey": account_key,
    "Uic": 211,
    "AssetType": "Stock",
    "OrderType": "Limit",
    "BuySell": "Buy",
    "OrderPrice": "220",
    "Amount": 1,
    "ManualOrder": True,
    "OrderDuration": {
        "DurationType": "DayOrder"
    },
    "OrderRelation": "StandAlone",
    "OrderContext": {
        "LastSeenClientBidPrice": 214.35,
        "LastSeenClientAskPrice": 214.41
    },
    "AppHint": 17039617
}



# Send the POST request
response = requests.post(url, json=payload, headers=headers)

# Handle the response
if response.status_code == 200:
    print("Order placed successfully!")
    print(response.json())
else:
    print("Failed to place order:")
    print(response.status_code, response.text)
