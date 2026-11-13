# Extended Trading Hours (ETH)

Runnable examples for US pre-market and post-market trading, using the existing
`requests` and `python-dotenv` dependencies. Run all commands from the repository
root. These are short-lived REST examples, not a trading bot or streaming client.

## Setup

Create and activate a virtual environment, install the root requirements, and
configure the existing `.env` file:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Activate it again in each new terminal before running the examples. If you see
`ModuleNotFoundError: No module named 'dotenv'`, the current Python does not have
`python-dotenv` installed; activate this environment or run the samples using
`.venv/bin/python` directly.

```dotenv
OPEN_API_BASE_URL=https://gateway.saxobank.com/sim/openapi/
ACCESS_TOKEN=your_simulation_access_token
ACCOUNT_KEY=your_account_key
CLIENT_KEY=your_client_key
```

Start in simulation. Obtain a [simulation token](https://www.developer.saxo/openapi/token)
or use the repository's [authentication samples](../README.md#authentication).
If `ACCESS_TOKEN` is absent, the examples prompt for it with hidden input. They do
not initiate OAuth or refresh tokens; obtain a new token when it expires. Never
commit tokens or real account identifiers.

Get `ClientKey` from `GET /port/v1/clients/me` and account keys from
`GET /port/v1/accounts/me`. Alternatively, pass `--account-key` and `--client-key`
where applicable. The examples print requests and responses, which may contain
account information, but never print the Authorization header.

Choose a UIC available in your environment. `211` below is illustrative, not a
guarantee of availability or ETH eligibility. `--asset-type` defaults to `Stock`;
`CfdOnStock` is also supported by these examples. The API remains authoritative for
instrument availability, price subscriptions, permissions, and trading constraints.

## 1. Client and Instrument Eligibility

```bash
python3 extended_hours/eth_samples.py eligibility --uic 211
```

Calls `GET /port/v1/clients/me` and
`GET /ref/v1/instruments/details/{Uic}/{AssetType}` with
`FieldGroups=TradingSessions` and displays:

| Field | How to use it |
| --- | --- |
| `AllowedTradingSessions` | The client must have `All`. `Regular` means regular hours only. Saxo sets this; an app cannot enable it through OpenAPI. |
| `IsExtendedTradingHoursEnabled` | Must be `true` for the instrument. Client permission alone is insufficient. |
| `TradingSessions.Sessions[]` | Read `StartTime`, `EndTime` and `State` for the instrument's schedule. `PreMarket` and `PostMarket` identify extended sessions. Do not hard-code US session times. |

Missing eligibility fields do not count as permission. Eligibility does not mean
that the instrument is currently trading or that a particular order will pass validation.

## 2. Session-Aware Prices

```bash
python3 extended_hours/eth_samples.py prices --uic 211
```

Requests `GET /trade/v1/infoprices` with
`FieldGroups=Quote,InstrumentPriceDetails`. During `Quote.MarketState=PreMarket`
or `PostMarket`, read `InstrumentPriceDetails.ExtendedTradingHoursPriceData`:

| Field | Meaning |
| --- | --- |
| `Ask`, `Bid`, `Mid` | ETH ask, bid and mid prices. |
| `LastTradedPrice` | Last trade in the extended session. |
| `LastTradedPriceTime` | UTC timestamp of that trade. |
| `NetChange`, `PercentChange` | Change in the extended session. |
| `Price` | Same as `LastTradedPrice` for Stock and CfdOnStock. |

For example, the relevant part of a response can look like:

```json
{
  "Quote": {"MarketState": "PreMarket"},
  "InstrumentPriceDetails": {
    "IsMarketOpen": false,
    "ExtendedTradingHoursPriceData": {
      "Bid": 150.05,
      "Ask": 150.12,
      "Mid": 150.085,
      "LastTradedPrice": 150.10,
      "LastTradedPriceTime": "2026-10-22T12:15:03Z",
      "Price": 150.10,
      "NetChange": 0.85,
      "PercentChange": 0.57
    }
  }
}
```

`IsMarketOpen=false` does not exclude pre/post-market trading. Use
`Quote.MarketState` to choose the price source. The ETH object is only returned
during extended hours; if missing then, the sample reports it as unavailable,
without presenting a regular quote as an ETH quote. Outside extended sessions,
the sample displays `Quote` instead. Prices are displayed, never used to generate orders.

For price subscriptions on `/trade/v1/prices` or `/trade/v1/infoprices`, request the
same `InstrumentPriceDetails` field group and read the same nested object.
Apply streamed deltas to your snapshot before selecting the price source.

## 3. Preview, Precheck and Place a Limit Order

The default action is a local preview: it needs no token, makes no API calls and
creates no order. An account key is needed to show the payload; a placeholder is
sufficient for a local preview:

```bash
python3 extended_hours/eth_samples.py order --account-key example --uic 211 --side Buy --amount 10 --limit-price 150
```

With a real simulation account key configured, precheck the same request:

```bash
python3 extended_hours/eth_samples.py order --uic 211 --side Buy --amount 10 --limit-price 150 --action precheck
```

This checks eligibility and calls `POST /trade/v2/orders/precheck`, without placing
an order. Inspect the returned validation result, costs and margin impact before
proceeding. A successful HTTP response alone is not proof of an accepted precheck.
The sample prints the full response; it does not interpret acceptance or chain
precheck into automatic placement. Precheck does not guarantee later acceptance.

**The next command submits an order and may execute immediately.** It uses the
configured environment, including live if you configured a live base URL. Review
the account, instrument, side, quantity and limit before running it:

```bash
python3 extended_hours/eth_samples.py order --uic 211 --side Buy --amount 10 --limit-price 150 --action place
```

Placement separately rechecks ETH eligibility and calls `POST /trade/v2/orders`.
No order request is retried automatically. If a placement times out, check your
orders before submitting again, since the first request may have succeeded.
The sample does not cancel the resulting order automatically.

The payload explicitly shows the important fields:

```json
{
  "AccountKey": "your_account_key",
  "Uic": 211,
  "AssetType": "Stock",
  "BuySell": "Buy",
  "Amount": 10,
  "OrderType": "Limit",
  "OrderPrice": 150,
  "OrderDuration": {"DurationType": "DayOrder"},
  "ExecuteAtTradingSession": "All",
  "ManualOrder": true
}
```

- `All` allows execution in **pre-market, regular and post-market**, not ETH only.
- Pass `--trading-session Regular` to compare regular-only behavior. The API also
  defaults to `Regular` when the field is omitted; this ETH sample explicitly defaults to `All`.
- Only **limit** orders can use `All`. Market, stop, stop-limit and trailing-stop
  orders cannot. The sample intentionally exposes no other order type.
- A related take-profit **limit** may use `All`; a related stop-loss cannot.
  Stops are triggered only by regular-session prices, so they do not protect
  positions during extended hours.
- An unfilled ETH limit `DayOrder` continues into post-market. An ETH GTC order
  remains working for the next pre-market under the currently documented behavior;
  this may change. The sample uses `DayOrder` only.
- `ManualOrder=true` represents a user-entered order. Do not reuse that designation
  unchanged for automatically generated orders.

### Modifying an Existing Order

`ExecuteAtTradingSession` is immutable after placement. For a price amendment,
omit it from `PATCH /trade/v2/orders` (or send its existing value):

```json
{
  "AccountKey": "your_account_key",
  "OrderId": "your_order_id",
  "AssetType": "Stock",
  "OrderType": "Limit",
  "OrderPrice": 149.50
}
```

This amendment payload is illustrative and is not sent by the CLI. To switch
between `Regular` and `All`, cancel the existing order and place a new one instead.
Account for fills that may occur before cancellation is confirmed.

### ETH Validation Errors

| Error code | Meaning |
| --- | --- |
| `ClientNotEnabledForExtendedTradingHours` | Client does not allow `All`. |
| `InstrumentNotSupportedForExtendedHours` | Instrument is not ETH-enabled; also returned by precheck. |
| `OnlyLimitOrderAllowedForExtendedHours` | A non-limit order was sent with `All`. |
| `ExtendedHoursTradingCannotBeChanged` | An amendment tried to change the order's session setting. |

The CLI checks both eligibility conditions before ETH precheck or placement.
Server validation still applies; API error bodies are displayed without retries.

## 4. Balances and Portfolio Follow-Up

```bash
python3 extended_hours/eth_samples.py balances
python3 extended_hours/eth_samples.py portfolio --resource orders
python3 extended_hours/eth_samples.py portfolio --resource positions
python3 extended_hours/eth_samples.py portfolio --resource netpositions
```

`GET /port/v1/balances` returns regular-hours values at the top level and, for
ETH-enabled clients, `ExtendedTradingHoursData` with ETH-based values. The sample
shows the two views separately, including currency. **Do not add them together**
or replace missing ETH fields with zero.

The nested ETH fields are:

| Field | Meaning |
| --- | --- |
| `TotalValue` | Account value including unrealized positions, costs, cash and unbooked transactions. |
| `NonMarginPositionsValue` | Sum of non-margin instrument market values. |
| `UnrealizedPositionsValue` | Unrealized P/L and face value of positions, excluding costs. |
| `UnrealizedPositionsValueExcludingCostToClosePositions` | Unrealized P/L and face value excluding cost to close. |
| `CostToClosePositions` | Estimated closing costs; negative for costs charged. |
| `UnrealizedMarginProfitLoss` | Margin-instrument P/L excluding costs. |
| `UnrealizedMarginOpenProfitLoss`, `UnrealizedMarginClosedProfitLoss` | Open/closed intraday-netting P/L. |
| `MarginAvailableForTrading` | Remaining collateral for margin trading. |
| `MarginUsedByCurrentPositions` | Maintenance margin used; negative for margin charged. |
| `InitialMarginUncertainty`, `MaintenanceMarginUncertainty` | Respective margin uncertainty values. |
| `UncertaintyValue` | ETH uncertainty deduction; negative for margin charged to initial margin available. |

Maintenance margin remains based on regular-hours prices. Initial margin uses
the less favourable of regular and ETH prices: an ETH loss can reduce available
initial margin through uncertainty deductions, while an ETH gain does not increase it.

Portfolio orders return the original `ExecuteAtTradingSession`. Orders,
`PositionView` and `NetPositionView` may have `CurrentPriceType` equal to `EthAsk`,
`EthBid`, `EthLastTradedPrice`, `EthMarkToMarket`, `EthNetChange` or `EthPercentChange`.
Those values identify ETH-based prices and derived valuations, not the order's
execution permission. The examples print raw responses, preserving unknown enum
values rather than rejecting them. Portfolio examples show one page; follow
`__next` for additional results.

The same ETH fields appear in balance and order subscriptions. ENS
`/ens/v1/activities` does **not** yet expose the ETH order properties; use portfolio
orders rather than ENS to determine the execution-session setting.

## 5. Charts With and Without Extended Hours

```bash
python3 extended_hours/eth_samples.py charts --uic 211
python3 extended_hours/eth_samples.py charts --uic 211 --extended-hours
```

Calls `GET /chart/v3/charts` with an explicit `ExtendedHoursEnabled=false` or
`true`, respectively, using one-minute bars (`Horizon=1`). The API default is
`false`. Read each sample's `MarketTradingState`: `PreMarket`, `Automated`
(regular session), `PostMarket`, or `None` (unavailable). Do not confuse this field
with `Quote.MarketState`. Only ETH-configured instruments provide ETH samples.

Chart subscriptions on `POST /chart/v3/charts/subscriptions` also support
`ExtendedHoursEnabled`; use `true` in the subscription arguments to include ETH.

## Offline Checks

```bash
python3 -m unittest extended_hours.test_eth_samples -v
python3 extended_hours/eth_samples.py --help
```

Tests mock all HTTP calls and never place orders. They cover eligibility, session
selection, missing ETH prices/balances, chart flags, preview/precheck/placement
routing, positive finite inputs, and non-retried failures.

## References

- [ETH integration guide (internal wiki)](https://wiki/pages/viewpage.action?pageId=535933891)
- [ETH release note (internal wiki)](https://wiki/pages/viewpage.action?pageId=535544327)
- [OpenAPI reference](https://www.developer.saxo/openapi/referencedocs)