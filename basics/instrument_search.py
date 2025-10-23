import requests
from typing import Optional, List, Dict
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils.logging_utils import setup_logging
from utils.logging_utils import raise_critical
import logging

# Initialize logging
setup_logging()

API_URL = "https://gateway.saxobank.com/sim/openapi"
BEARER_TOKEN = "eyJhbGciOiJFUzI1NiIsIng1dCI6IjI3RTlCOTAzRUNGMjExMDlBREU1RTVCOUVDMDgxNkI2QjQ5REEwRkEifQ.eyJvYWEiOiI3Nzc3MCIsImlzcyI6Im9hIiwiYWlkIjoiNjYyMSIsInVpZCI6IjBZakxGMVktSktjU3NOVGhSekVFVEE9PSIsImNpZCI6IjBZakxGMVktSktjU3NOVGhSekVFVEE9PSIsImlzYSI6IkZhbHNlIiwidGlkIjoiMTE2NDgiLCJzaWQiOiIyOTQxMjMxMTkzZGE0MjQ3YjVkMzNjNjk4YTFjZDRkOSIsImRnaSI6Ijg0IiwiZXhwIjoiMTc1Njk4ODA3MCIsIm9hbCI6IjFGIiwiaWlkIjoiZWZmMzVlNzMxYWU4NDBmNTljZDAwOGRkNzEwMDk5NDAifQ.H1UnReCUtPbSt-82Co1vnAGqB48UbM2f5w1Crio-Og91u83eAD_g8-GP2gvzcbEYZNva6WaV2MQ77dOoYBw8EA"
HEADERS = {
    "Authorization": f"Bearer {BEARER_TOKEN}"
}

def get_exchanges() -> List[Dict]:
    """Fetches and returns a sorted list of exchanges."""
    url = f"{API_URL}/ref/v1/exchanges?$top=1000"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        exchanges = response.json().get('Data', [])
        sorted_exchanges = sorted(exchanges, key=lambda x: x['Name'].upper())
        logging.important(f"Fetched {len(sorted_exchanges)} exchanges.")
        return sorted_exchanges
    except requests.RequestException as e:
        logging.error(f"Failed to fetch exchanges: {e}")
        return []

def find_instrument(
    account_key: str,
    keywords: str,
    exchange_id: str = '-',
    asset_type: str = 'Stock',
    include_non_tradable: bool = False,
    can_multi_leg_order: bool = False
) -> Optional[Dict]:
    """Searches for instruments based on filters."""
    params = {
        "$top": 200,
        "Keywords": keywords,
        "IncludeNonTradable": str(include_non_tradable).lower()
    }
    if exchange_id != '-':
        params["ExchangeId"] = exchange_id
    if asset_type != '-':
        params["AssetTypes"] = asset_type
    if can_multi_leg_order:
        params["CanParticipateInMultiLegOrder"] = "true"

    try:
        response = requests.get(f"{API_URL}/ref/v1/instruments", headers=HEADERS, params=params)
        response.raise_for_status()
        instruments = response.json().get('Data', [])
        logging.important(f"Found {len(instruments)} instruments for keyword '{keywords}'.")
        for instrument in instruments:
            logging.debug(f"{instrument['AssetType']} {instrument['Description']}")
        return instruments[0] if instruments else None
    except requests.RequestException as e:
        logging.error(f"Failed to find instruments: {e}")
        return None

def get_details(instrument: Dict, asset_type: str) -> Optional[Dict]:
    """Fetches detailed information about a specific instrument."""
    identifier = instrument['Identifier']
    summary_type = instrument['SummaryType']

    if summary_type == "ContractOptionRoot":
        url_path = f"/ref/v1/instruments/contractoptionspaces/{identifier}"
    elif summary_type == "ContractFutures":
        url_path = f"/ref/v1/instruments/futuresspaces/{identifier}"
    else:
        url_path = f"/ref/v1/instruments/details/{identifier}/{asset_type}"

    full_url = API_URL + url_path
    logging.info(f"Fetching details from {full_url}")

    try:
        response = requests.get(full_url, headers=HEADERS)
        response.raise_for_status()
        details = response.json()
        logging.important("Instrument details fetched successfully.")
        return details
    except requests.RequestException as e:
        logging.error(f"Failed to fetch instrument details: {e}")
        return None


# Example usage
if __name__ == "__main__":
    account_key = "your_account_key"
    keywords = "AAPL"

    exchanges = get_exchanges()
    if not exchanges:
        raise_critical("Exchange list is empty. Cannot proceed.")

    instrument = find_instrument(account_key, keywords)
    if not instrument:
        raise_critical(f"No instrument found for keyword '{keywords}'.")

    details = get_details(instrument, instrument['AssetType'])
    if details:
        print(details)
    else:
        raise_critical("Instrument details could not be retrieved.")