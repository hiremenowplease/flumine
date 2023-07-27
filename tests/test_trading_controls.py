from collections import defaultdict
from unittest import mock

import pytest

from flumine.controls.tradingcontrols import CustomStrategyExposure
from flumine.markets.blotter import Blotter
from flumine.order.orderpackage import OrderPackageType
from flumine.order.ordertype import LimitOnCloseOrder, LimitOrder
from flumine.utils import get_default_dict


def get_exposures_func_mock(strategy, market, order, return_exposure):
    if "max_order_exposure" == return_exposure:
        return strategy.back_max_order_exposure if order.side == "BACK" else strategy.lay_max_order_exposure
    else:
        return strategy.back_max_selection_exposure if order.side == "BACK" else strategy.lay_max_selection_exposure


class TestEsFlumine:
    @pytest.fixture(scope="session", autouse=True)
    def trading_controls(self):
        market = mock.Mock(context={})
        market.blotter = Blotter("market_id")
        market.market_id = "market_id"
        mock_flumine = mock.Mock()
        mock_flumine.markets.markets = {"market_id": market}
        return CustomStrategyExposure(mock_flumine)

    @pytest.fixture
    def exposure_settings(self):
        return {
            "COUNTRY": {"BACK": (200, 200), "LAY": (50, 50)},
            "PROVINCIAL": {"BACK": (300, 300), "LAY": (50, 50)},
            "METRO": {"BACK": (400, 400), "LAY": (50, 50)},
            "LOCATION_UNKNOWN": {"BACK": (200, 200), "LAY": (50, 50)},
        }

    @pytest.fixture
    def mock_strategy(self):
        strategy = mock.Mock(
            max_stake=99999999,
            back_max_order_exposure=99999999,
            lay_max_order_exposure=99999999,
            exposure_settings=None,
            get_exposures_func=get_exposures_func_mock,
        )
        mock_runner_context = mock.Mock()
        strategy.validate_order.return_value = True
        strategy.get_runner_context.return_value = mock_runner_context
        return strategy

    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._on_error")
    def test_validate_strategy_errors_on_invalid_order(self, mock_on_error, trading_controls):
        mock_order = mock.Mock(market_id="market_id", lookup=(1, 2, 3))
        mock_order.trade.strategy.validate_order.return_value = False
        mock_runner_context = mock.Mock()
        mock_order.trade.strategy.get_runner_context.return_value = mock_runner_context

        trading_controls._validate(mock_order, OrderPackageType.PLACE)

        mock_on_error.assert_called_with(
            mock_order,
            mock_order.violation_msg,
        )

    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._get_order_to_win_lose_amount")
    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._get_order_stake")
    def test_validate_strategy_validates_order(
        self, mock_get_order_stake, mock_order_to_win_lose_amount, trading_controls, mock_strategy
    ):
        mock_order_to_win_lose_amount.return_value = 20
        mock_get_order_stake.return_value = 5

        mock_order = mock.Mock(market_id="market_id", lookup=(1, 2, 3), side="BACK")
        mock_strategy.max_stake = 100
        mock_strategy.back_max_selection_exposure = 75
        mock_strategy.back_max_order_exposure = 50

        mock_order.trade.strategy = mock_strategy
        trading_controls._validate(mock_order, OrderPackageType.PLACE)

    @pytest.mark.parametrize(
        "order_side, order_type, max_order_exposure, expected_order",
        [
            ("BACK", LimitOrder(size=100, price=6), 400, LimitOrder(size=80, price=6)),
            ("BACK", LimitOrder(size=1, price=21), 20, LimitOrder(size=1, price=21)),
            ("LAY", LimitOrder(size=101, price=21), 2000, LimitOrder(size=100, price=21)),
            ("LAY", LimitOrder(size=5, price=11), 10, LimitOrder(size=1, price=11)),
            ("BACK", LimitOnCloseOrder(liability=100, price=2), 50, LimitOnCloseOrder(liability=50, price=2)),
            (
                "BACK",
                LimitOnCloseOrder(liability=100, price=21),
                1000,
                LimitOnCloseOrder(liability=50, price=21),
            ),
            (
                "LAY",
                LimitOnCloseOrder(liability=2000, price=2),
                1000,
                LimitOnCloseOrder(liability=1000, price=2),
            ),
            (
                "LAY",
                LimitOnCloseOrder(liability=2000, price=21),
                500,
                LimitOnCloseOrder(liability=500, price=21),
            ),
        ],
    )
    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._get_order_stake")
    def test_validate_strategy_adjusts_order_to_max_order(
        self,
        mock_get_order_stake,
        order_side,
        order_type,
        max_order_exposure,
        expected_order,
        trading_controls,
        mock_strategy,
    ):
        mock_order = mock.Mock(market_id="market_id", lookup=(1, 2, 3), side=order_side)
        mock_order.order_type = order_type

        if order_side == "BACK":
            mock_strategy.back_max_order_exposure = max_order_exposure
            mock_strategy.back_max_selection_exposure = 99999999
        elif order_side == "LAY":
            mock_strategy.lay_max_order_exposure = max_order_exposure
            mock_strategy.lay_max_selection_exposure = 99999999

        mock_get_order_stake.return_value = 1
        mock_order.trade.strategy = mock_strategy

        trading_controls._validate(mock_order, OrderPackageType.PLACE)

        assert mock_order.order_type.__dict__ == expected_order.__dict__

    @pytest.mark.parametrize(
        "order_side, order_type, profit_if_win, expected_potential_exposure, max_selection_exposure",
        [
            ("BACK", LimitOrder(size=100, price=5), 301, 701, 300),
            ("BACK", LimitOrder(size=100, price=5), 500, 900, 499),
            ("LAY", LimitOrder(size=100, price=21), -2000, 4000, 2000),
            ("LAY", LimitOrder(size=5, price=11), -40, 90, 40),
            ("BACK", LimitOnCloseOrder(liability=100, price=2), 100, 200, 100),
            ("BACK", LimitOnCloseOrder(liability=100, price=21), 2000, 4000, 2000),
            ("LAY", LimitOnCloseOrder(liability=2000, price=2), -2000, 4000, 2000),
            ("LAY", LimitOnCloseOrder(liability=2000, price=21), -10, 2010, 10),
        ],
    )
    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._get_exposures")
    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._on_error")
    def test_validate_strategy_errors_on_exposure_exceeding_potential_selection_exposure(
        self,
        mock_on_error,
        mock_get_exposures,
        order_side,
        order_type,
        profit_if_win,
        expected_potential_exposure,
        max_selection_exposure,
        trading_controls,
        mock_strategy,
    ):
        mock_get_exposures.return_value = {
            "matched_profit_if_win": profit_if_win,
        }

        mock_order = mock.Mock(market_id="market_id", lookup=(1, 2, 3), side=order_side)

        mock_strategy.max_stake = 99999999
        mock_strategy.back_max_order_exposure = 99999999
        mock_strategy.lay_max_order_exposure = 99999999
        mock_order.selection_id = 666
        mock_strategy.context = {}
        mock_strategy.name = "my_strategy"
        mock_order.order_type = order_type
        trading_controls.flumine.markets.markets["market_id"].context = {
            "strategies_over_limit": defaultdict(get_default_dict(list))
        }

        if order_side == "BACK":
            mock_strategy.back_max_selection_exposure = max_selection_exposure
        else:
            mock_strategy.lay_max_selection_exposure = max_selection_exposure
        mock_order.trade.strategy = mock_strategy

        trading_controls._validate(mock_order, OrderPackageType.PLACE)

        mock_on_error.assert_called_with(
            mock_order,
            "Potential selection exposure ({0:.2f}) for my_strategy is greater than the strategy.max_selection_exposure ({1})".format(
                expected_potential_exposure,
                max_selection_exposure,
            ),
        )

        assert trading_controls.flumine.markets.markets["market_id"].context == {
            "strategies_over_limit": {"my_strategy": {"market_id": [666]}}
        }

    @pytest.mark.parametrize(
        "order_side, order_type, profit_if_win, max_order_exposure, max_selection_exposure, max_stake, expected_order",
        [
            ("BACK", LimitOrder(size=100, price=2), 100, 50, 175, 9999, LimitOrder(size=50, price=2)),
            ("BACK", LimitOrder(size=100, price=5), 100, 100, 150, 2, LimitOrder(size=2, price=5)),
            ("BACK", LimitOrder(size=1000, price=3), 900, 50, 920, 80, LimitOrder(size=10, price=3)),
            ("LAY", LimitOrder(size=100, price=21), -500, 100, 550, 100, LimitOrder(size=2.5, price=21)),
            (
                "LAY",
                LimitOrder(size=1000, price=1.01),
                -500,
                100,
                550,
                100,
                LimitOrder(size=100, price=1.01),
            ),
            ("LAY", LimitOrder(size=1000, price=2), -900, 50, 920, 70, LimitOrder(size=20, price=2)),
            (
                "BACK",
                LimitOnCloseOrder(liability=1000, price=11),
                900,
                100,
                950,
                100,
                LimitOnCloseOrder(liability=5, price=11),
            ),
            (
                "LAY",
                LimitOnCloseOrder(liability=1000, price=3),
                -800,
                250,
                1000,
                500,
                LimitOnCloseOrder(liability=200, price=3),
            ),
        ],
    )
    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._get_exposures")
    def test_validate_strategy_adjusts_to_max_stake_and_max_order_and_max_potential_selection_exposure(
        self,
        mock_get_exposures,
        order_side,
        order_type,
        profit_if_win,
        max_order_exposure,
        max_selection_exposure,
        max_stake,
        expected_order,
        trading_controls,
        mock_strategy,
    ):
        mock_get_exposures.return_value = {
            "matched_profit_if_win": profit_if_win,
        }

        mock_order = mock.Mock(market_id="market_id", lookup=(1, 2, 3), side=order_side)
        mock_order.order_type = order_type

        mock_strategy.max_stake = max_stake

        if order_side == "BACK":
            mock_strategy.back_max_order_exposure = max_order_exposure
            mock_strategy.back_max_selection_exposure = max_selection_exposure
        else:
            mock_strategy.lay_max_order_exposure = max_order_exposure
            mock_strategy.lay_max_selection_exposure = max_selection_exposure

        mock_order.trade.strategy = mock_strategy
        trading_controls._validate(mock_order, OrderPackageType.PLACE)

        assert mock_order.order_type.__dict__ == expected_order.__dict__

    @pytest.mark.parametrize(
        "order_side, order_type, current_to_win, current_to_lose, max_selection_exposure",
        [
            ("BACK", LimitOrder(size=100, price=5), 100, 0, 1000),
            ("BACK", LimitOrder(size=100, price=5), 100, 0, 700),
            ("LAY", LimitOrder(size=100, price=21), 0, -50, 3000),
            ("LAY", LimitOrder(size=5, price=11), 0, -20, 3000),
            ("BACK", LimitOnCloseOrder(liability=100, price=2), 100, 0, 200),
            ("BACK", LimitOnCloseOrder(liability=100, price=21), 50, 0, 2500),
            ("LAY", LimitOnCloseOrder(liability=2000, price=2), 0, -1, 3000),
            ("LAY", LimitOnCloseOrder(liability=2000, price=21), 0, -10, 5000),
        ],
    )
    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._get_exposures")
    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._on_error")
    def test_validate_strategy_validates_orders(
        self,
        mock_on_error,
        mock_get_exposures,
        order_side,
        order_type,
        current_to_win,
        current_to_lose,
        max_selection_exposure,
        trading_controls,
        mock_strategy,
    ):
        mock_get_exposures.return_value = {
            "matched_profit_if_win": current_to_win,
            "worst_possible_profit_on_win": current_to_lose,
        }

        if order_side == "BACK":
            mock_strategy.back_max_selection_exposure = max_selection_exposure
        else:
            mock_strategy.lay_max_selection_exposure = max_selection_exposure

        mock_order = mock.Mock(market_id="market_id", lookup=(1, 2, 3), side=order_side)
        mock_order.trade.strategy = mock_strategy

        mock_order.order_type = order_type

        trading_controls._validate(mock_order, OrderPackageType.PLACE)

        assert not mock_on_error.called

    @pytest.mark.parametrize(
        "order_side, order_type, remaining_exposure, expected_order",
        [
            ("BACK", LimitOrder(size=100, price=2), 50, LimitOrder(size=50, price=2)),
            ("BACK", LimitOrder(size=100, price=5), 100, LimitOrder(size=25, price=5)),
            ("LAY", LimitOrder(size=100, price=21), 200, LimitOrder(size=10, price=21)),
            ("LAY", LimitOrder(size=5, price=11), 10, LimitOrder(size=1, price=11)),
            ("BACK", LimitOnCloseOrder(liability=100, price=2), 50, LimitOnCloseOrder(liability=50, price=2)),
            (
                "BACK",
                LimitOnCloseOrder(liability=100, price=6),
                100,
                LimitOnCloseOrder(liability=20, price=6),
            ),
            (
                "LAY",
                LimitOnCloseOrder(liability=1000, price=11),
                100,
                LimitOnCloseOrder(liability=100, price=11),
            ),
            ("LAY", LimitOnCloseOrder(liability=50, price=3), 10, LimitOnCloseOrder(liability=10, price=3)),
        ],
    )
    def test_given_remaining_exposure_order_is_adjusted(
        self, order_side, order_type, remaining_exposure, expected_order
    ):
        trading_control = CustomStrategyExposure(mock.Mock())
        mock_order = mock.Mock(side=order_side)
        mock_order.order_type = order_type

        trading_control._update_order_to_meet_max_exposure(mock_order, remaining_exposure)

        assert mock_order.order_type.__dict__ == expected_order.__dict__

    @pytest.mark.f
    @pytest.mark.parametrize(
        "order_side, order_type, profit_if_win, max_order_exposure, max_selection_exposure, max_stake, expected_potential_exposure",
        [
            ("BACK", LimitOrder(size=100, price=5), 108, 108, 109, 20, 188),
            ("BACK", LimitOrder(size=1000, price=3), 918, 50, 919, 80, 968),
            ("LAY", LimitOrder(size=100, price=21), -500, 100, 501, 100, 600),
        ],
    )
    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._on_error")
    @mock.patch("flumine.controls.tradingcontrols.CustomStrategyExposure._get_exposures")
    def test_validate_strategy_updates_context_for_runners_that_have_remaining_exposure_less_than_1(
        self,
        mock_get_exposures,
        mock_on_error,
        order_side,
        order_type,
        profit_if_win,
        max_order_exposure,
        max_selection_exposure,
        max_stake,
        expected_potential_exposure,
        trading_controls,
        mock_strategy,
    ):
        mock_get_exposures.return_value = {
            "matched_profit_if_win": profit_if_win,
        }

        mock_order = mock.Mock(market_id="market_id", selection_id=123, lookup=(1, 2, 3), side=order_side)
        mock_order.order_type = order_type

        mock_strategy.context = {}
        mock_strategy.name = "my_strategy"
        mock_strategy.max_stake = max_stake

        trading_controls.flumine.markets.markets["market_id"].context = {
            "strategies_over_limit": defaultdict(get_default_dict(list))
        }

        if order_side == "BACK":
            mock_strategy.back_max_order_exposure = max_order_exposure
            mock_strategy.back_max_selection_exposure = max_selection_exposure
        else:
            mock_strategy.lay_max_order_exposure = max_order_exposure
            mock_strategy.lay_max_selection_exposure = max_selection_exposure

        mock_order.trade.strategy = mock_strategy
        trading_controls._validate(mock_order, OrderPackageType.PLACE)

        mock_on_error.assert_called_with(
            mock_order,
            "Potential selection exposure ({0:.2f}) for my_strategy is greater than the strategy.max_selection_exposure ({1})".format(
                expected_potential_exposure,
                max_selection_exposure,
            ),
        )
