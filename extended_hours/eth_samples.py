#!/usr/bin/env python3
"""Standalone Extended Trading Hours examples. Run with --help for commands."""

import argparse
import getpass
import json
import math
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


EXTENDED_SESSIONS = ("PreMarket", "PostMarket")
BALANCE_FIELDS = (
    "CostToClosePositions", "InitialMarginUncertainty",
    "MaintenanceMarginUncertainty", "MarginAvailableForTrading",
    "MarginUsedByCurrentPositions", "NonMarginPositionsValue", "TotalValue",
    "UncertaintyValue", "UnrealizedMarginClosedProfitLoss",
    "UnrealizedMarginOpenProfitLoss", "UnrealizedMarginProfitLoss",
    "UnrealizedPositionsValue",
    "UnrealizedPositionsValueExcludingCostToClosePositions",
)


def show(label, data):
    print("\n{}".format(label))
    print(json.dumps(data, indent=2))


class OpenApi:
    def __init__(self, base_url, access_token):
        self.base_url = base_url.rstrip("/") + "/"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Bearer " + access_token})

    def request(self, method, path, params=None, payload=None):
        show("{} {}".format(method, path), params if params is not None else payload)
        response = self.session.request(
            method, self.base_url + path, params=params, json=payload, timeout=30
        )
        if not response.ok:
            raise RuntimeError("OpenAPI returned {}: {}".format(
                response.status_code, response.text
            ))
        data = response.json()
        show("Response", data)
        return data


def eligibility(api, uic, asset_type, account_key=None):
    client = api.request("GET", "port/v1/clients/me")
    params = {"FieldGroups": "TradingSessions"}
    if account_key:
        params["AccountKey"] = account_key
    instrument = api.request(
        "GET", "ref/v1/instruments/details/{}/{}".format(uic, asset_type),
        params=params,
    )
    enabled = (
        client.get("AllowedTradingSessions") == "All"
        and instrument.get("IsExtendedTradingHoursEnabled") is True
    )
    show("ETH eligibility (both conditions must be true)", {
        "AllowedTradingSessions": client.get("AllowedTradingSessions"),
        "IsExtendedTradingHoursEnabled": instrument.get("IsExtendedTradingHoursEnabled"),
        "Eligible": enabled,
        "TradingSessions": instrument.get("TradingSessions"),
    })
    return enabled


def select_price_data(response):
    """Never label a regular quote as an ETH quote when ETH data is absent."""
    quote = response.get("Quote", {})
    if quote.get("MarketState") in EXTENDED_SESSIONS:
        return response.get("InstrumentPriceDetails", {}).get("ExtendedTradingHoursPriceData")
    return quote


def prices(api, args):
    response = api.request("GET", "trade/v1/infoprices", params={
        "AccountKey": args.account_key,
        "Uic": args.uic,
        "AssetType": args.asset_type,
        "FieldGroups": "Quote,InstrumentPriceDetails",
    })
    selected = select_price_data(response)
    show("Price data for Quote.MarketState", selected)
    if selected is None:
        print("ETH price data is unavailable; do not substitute a regular-hours quote.")
    print("Use Quote.MarketState, not IsMarketOpen, to identify pre/post-market.")


def charts(api, args):
    api.request("GET", "chart/v3/charts", params={
        "AccountKey": args.account_key,
        "Uic": args.uic,
        "AssetType": args.asset_type,
        "Horizon": 1,
        "Count": 20,
        "ExtendedHoursEnabled": "true" if args.extended_hours else "false",
    })
    print("Read each sample's MarketTradingState: PreMarket, Automated, PostMarket or None.")


def balance_comparison(response):
    extended = response.get("ExtendedTradingHoursData")
    return {
        "Currency": response.get("Currency"),
        "RegularHours": {field: response[field] for field in BALANCE_FIELDS if field in response},
        "ExtendedTradingHoursData": (
            {field: extended[field] for field in BALANCE_FIELDS if field in extended}
            if isinstance(extended, dict) else None
        ),
    }


def balances(api, args):
    response = api.request("GET", "port/v1/balances", params={
        "ClientKey": args.client_key, "AccountKey": args.account_key,
    })
    show("Regular and ETH valuations (not added together)", balance_comparison(response))
    if response.get("ExtendedTradingHoursData") is None:
        print("No ETH balance data returned; missing values are not zero.")


def portfolio(api, args):
    paths = {
        "orders": "port/v1/orders/me",
        "positions": "port/v1/positions/me",
        "netpositions": "port/v1/netpositions/me",
    }
    params = {"AccountKey": args.account_key}
    if args.resource == "positions":
        params["FieldGroups"] = "PositionBase,PositionView"
    elif args.resource == "netpositions":
        params["FieldGroups"] = "NetPositionBase,NetPositionView"
    api.request("GET", paths[args.resource], params=params)
    print("Orders expose ExecuteAtTradingSession. Read CurrentPriceType on orders,")
    print("PositionView or NetPositionView; Eth* values identify ETH-based valuations.")
    print("This is one page; use the response's __next link for additional results.")


def positive_number(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Must be a finite number greater than zero")
    return number


def limit_order(args):
    return {
        "AccountKey": args.account_key,
        "Uic": args.uic,
        "AssetType": args.asset_type,
        "BuySell": args.side,
        "Amount": args.amount,
        "OrderType": "Limit",
        "OrderPrice": args.limit_price,
        "OrderDuration": {"DurationType": "DayOrder"},
        "ExecuteAtTradingSession": args.trading_session,
        "ManualOrder": True,
    }


def order(api, args):
    payload = limit_order(args)
    show("Limit order request (All includes regular hours too)", payload)
    if args.action == "preview":
        print("Preview only. No API request made and no order created.")
        return
    if args.trading_session == "All" and not eligibility(
        api, args.uic, args.asset_type, args.account_key
    ):
        raise ValueError("Both client and instrument must be enabled for ETH.")
    if args.action == "precheck":
        api.request("POST", "trade/v2/orders/precheck", payload=payload)
    else:
        print("Submitting an order to the configured environment. No automatic retries.")
        api.request("POST", "trade/v2/orders", payload=payload)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("eligibility", "prices", "charts", "order", "balances", "portfolio"):
        command = commands.add_parser(name)
        command.add_argument("--account-key", default=os.getenv("ACCOUNT_KEY"))
        if name in ("eligibility", "prices", "charts", "order"):
            command.add_argument("--uic", type=int, required=True)
            command.add_argument("--asset-type", choices=("Stock", "CfdOnStock"), default="Stock")
        if name == "charts":
            command.add_argument("--extended-hours", action="store_true",
                                 help="Include ETH samples; otherwise regular hours only")
        elif name == "balances":
            command.add_argument("--client-key", default=os.getenv("CLIENT_KEY"))
        elif name == "portfolio":
            command.add_argument("--resource", choices=("orders", "positions", "netpositions"),
                                 default="orders")
        elif name == "order":
            command.add_argument("--side", choices=("Buy", "Sell"), required=True)
            command.add_argument("--amount", type=positive_number, required=True)
            command.add_argument("--limit-price", type=positive_number, required=True)
            command.add_argument("--trading-session", choices=("All", "Regular"), default="All")
            command.add_argument("--action", choices=("preview", "precheck", "place"),
                                 default="preview")
    return root


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    arguments = parser()
    args = arguments.parse_args()
    if args.command != "eligibility" and not args.account_key:
        arguments.error("Set ACCOUNT_KEY or pass --account-key.")
    if args.command == "balances" and not args.client_key:
        arguments.error("Set CLIENT_KEY or pass --client-key (from clients/me).")
    if args.command == "order" and args.action == "preview":
        order(None, args)
        return
    base_url = os.getenv("OPEN_API_BASE_URL")
    if not base_url:
        arguments.error("Set OPEN_API_BASE_URL; start with the simulation environment.")
    token = os.getenv("ACCESS_TOKEN") or getpass.getpass("Access token (hidden): ").strip()
    if not token:
        arguments.error("An access token is required.")
    api = OpenApi(base_url, token)
    try:
        if args.command == "eligibility":
            eligibility(api, args.uic, args.asset_type, args.account_key)
        else:
            {"prices": prices, "charts": charts, "balances": balances,
             "portfolio": portfolio, "order": order}[args.command](api, args)
    except (requests.RequestException, RuntimeError, ValueError) as error:
        arguments.exit(1, "{}\n".format(error))
    finally:
        api.session.close()


if __name__ == "__main__":
    main()