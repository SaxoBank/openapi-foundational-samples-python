import argparse
import unittest
from unittest.mock import Mock, patch

from extended_hours import eth_samples as samples


class ExtendedHoursTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.args = samples.parser().parse_args([
            "order", "--account-key", "account", "--uic", "211", "--side", "Buy",
            "--amount", "10", "--limit-price", "150",
        ])
        self.output = patch("builtins.print")
        self.output.start()
        self.addCleanup(self.output.stop)

    def test_limit_order_has_explicit_session_and_limit_fields(self):
        payload = samples.limit_order(self.args)
        self.assertEqual(payload["ExecuteAtTradingSession"], "All")
        self.assertEqual(payload["OrderType"], "Limit")
        self.assertEqual(payload["OrderPrice"], 150)
        self.assertEqual(payload["OrderDuration"], {"DurationType": "DayOrder"})
        self.args.trading_session = "Regular"
        self.assertEqual(samples.limit_order(self.args)["ExecuteAtTradingSession"], "Regular")

    def test_preview_never_calls_api(self):
        samples.order(self.api, self.args)
        self.api.request.assert_not_called()

    def test_eligibility_explicitly_requests_session_schedule(self):
        for account_key in (None, "account"):
            with self.subTest(account_key=account_key):
                self.api.request.side_effect = [
                    {"AllowedTradingSessions": "All"},
                    {"IsExtendedTradingHoursEnabled": True,
                     "TradingSessions": {"Sessions": []}},
                ]
                self.assertTrue(samples.eligibility(self.api, 211, "Stock", account_key))
                params = {"FieldGroups": "TradingSessions"}
                if account_key:
                    params["AccountKey"] = account_key
                self.api.request.assert_called_with(
                    "GET", "ref/v1/instruments/details/211/Stock", params=params
                )

    def test_precheck_and_place_have_separate_endpoints(self):
        for action, path in (("precheck", "trade/v2/orders/precheck"),
                             ("place", "trade/v2/orders")):
            with self.subTest(action=action):
                self.args.action = action
                self.api.request.side_effect = [
                    {"AllowedTradingSessions": "All"},
                    {"IsExtendedTradingHoursEnabled": True}, {},
                ]
                samples.order(self.api, self.args)
                self.api.request.assert_called_with(
                    "POST", path, payload=samples.limit_order(self.args)
                )

    def test_ineligible_or_missing_fields_block_eth_orders(self):
        for client, instrument in (
            ({"AllowedTradingSessions": "Regular"}, {"IsExtendedTradingHoursEnabled": True}),
            ({"AllowedTradingSessions": "All"}, {"IsExtendedTradingHoursEnabled": False}),
            ({}, {}),
        ):
            with self.subTest(client=client, instrument=instrument):
                self.api.reset_mock()
                self.api.request.side_effect = [client, instrument]
                self.args.action = "place"
                with self.assertRaises(ValueError):
                    samples.order(self.api, self.args)
                self.assertEqual(self.api.request.call_count, 2)

    def test_regular_order_does_not_require_eth_eligibility(self):
        self.args.action = "precheck"
        self.args.trading_session = "Regular"
        samples.order(self.api, self.args)
        self.api.request.assert_called_once_with(
            "POST", "trade/v2/orders/precheck", payload=samples.limit_order(self.args)
        )

    def test_price_selection_uses_market_state_not_is_market_open(self):
        for state in samples.EXTENDED_SESSIONS:
            with self.subTest(state=state):
                response = {
                    "Quote": {"MarketState": state, "Bid": 100},
                    "InstrumentPriceDetails": {
                        "IsMarketOpen": False,
                        "ExtendedTradingHoursPriceData": {"Bid": 101},
                    },
                }
                self.assertEqual(samples.select_price_data(response), {"Bid": 101})
                del response["InstrumentPriceDetails"]["ExtendedTradingHoursPriceData"]
                self.assertIsNone(samples.select_price_data(response))
        self.assertEqual(samples.select_price_data({
            "Quote": {"MarketState": "Open", "Bid": 100}
        }), {"MarketState": "Open", "Bid": 100})

    def test_balance_views_remain_separate_and_preserve_missing_values(self):
        response = {"Currency": "USD", "TotalValue": 100,
                    "ExtendedTradingHoursData": {"TotalValue": 90, "UncertaintyValue": -10}}
        result = samples.balance_comparison(response)
        self.assertEqual(result["RegularHours"], {"TotalValue": 100})
        self.assertEqual(result["ExtendedTradingHoursData"],
                         {"TotalValue": 90, "UncertaintyValue": -10})
        self.assertIsNone(samples.balance_comparison({})["ExtendedTradingHoursData"])

    def test_chart_flag_is_explicit(self):
        args = samples.parser().parse_args(["charts", "--uic", "211", "--extended-hours"])
        samples.charts(self.api, args)
        self.assertEqual(self.api.request.call_args.kwargs["params"]["ExtendedHoursEnabled"], "true")
        args.extended_hours = False
        samples.charts(self.api, args)
        self.assertEqual(self.api.request.call_args.kwargs["params"]["ExtendedHoursEnabled"], "false")

    def test_invalid_order_numbers_are_rejected(self):
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                samples.positive_number(value)

    def test_failed_requests_are_not_retried(self):
        with patch.object(samples.requests, "Session") as session:
            response = session.return_value.request.return_value
            response.ok = False
            response.status_code = 400
            response.text = '{"ErrorCode":"OnlyLimitOrderAllowedForExtendedHours"}'
            api = samples.OpenApi("https://example.test/openapi/", "test-token")
            with self.assertRaisesRegex(RuntimeError, "OnlyLimitOrderAllowedForExtendedHours"):
                api.request("POST", "trade/v2/orders", payload={})
            session.return_value.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()