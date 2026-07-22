import pytest
from src.strategy.simulators.sim0_libero import (
    calculate_kospi_trend, normalize_foreigner_score,
    calculate_decline_ratio, collect_signals, ensemble_breadth
)


class TestKospiTrend:
    def test_kospi_trend_positive(self):
        """KOSPI가 5일MA 위에서 +4.17% 상승"""
        trend = calculate_kospi_trend(2500, 2400)
        assert 4 < trend < 5

    def test_kospi_trend_negative(self):
        """KOSPI가 5일MA 아래에서 -4% 하락"""
        trend = calculate_kospi_trend(2400, 2500)
        assert -5 < trend < -3

    def test_kospi_trend_clipped_positive(self):
        """상승폭 150% → 클립 100"""
        trend = calculate_kospi_trend(5000, 2000)
        assert trend == 100

    def test_kospi_trend_clipped_negative(self):
        """하락폭 100% → 클립 -100"""
        trend = calculate_kospi_trend(0, 2000)
        assert trend == -100

    def test_kospi_trend_zero_ma5(self):
        """kospi_ma5 = 0일 때 0.0 반환 (0 나눗셈 방지)"""
        trend = calculate_kospi_trend(2500, 0)
        assert trend == 0.0

    def test_kospi_trend_negative_clipped(self):
        """극도 약세(-100%)를 -100으로 클립"""
        trend_extreme = calculate_kospi_trend(0, 2500)
        assert trend_extreme == -100


class TestForeignerScore:
    def test_foreigner_score_max_buy(self):
        """외국인 최대 매수: 100"""
        score = normalize_foreigner_score(100000000000)
        assert score == 100

    def test_foreigner_score_neutral(self):
        """외국인 중립: 0 → 50"""
        score = normalize_foreigner_score(0)
        assert score == 50

    def test_foreigner_score_max_sell(self):
        """외국인 최대 매도: -100000000000 → 0"""
        score = normalize_foreigner_score(-100000000000)
        assert score == 0


class TestDeclineRatio:
    def test_decline_ratio_all_rising(self):
        """모두 상승: 0%"""
        ratio = calculate_decline_ratio(0, 100)
        assert ratio == 0

    def test_decline_ratio_all_declining(self):
        """모두 낙폭: 100%"""
        ratio = calculate_decline_ratio(100, 0)
        assert ratio == 100

    def test_decline_ratio_half(self):
        """낙폭 50% 상승 50%: 50%"""
        ratio = calculate_decline_ratio(50, 50)
        assert ratio == 50


class TestCollectSignals:
    def test_collect_signals_integration(self):
        """4개 신호 통합 테스트"""
        signals = collect_signals(
            {'breadth': 60, 'declining': 30, 'rising': 70},
            {'price': 2500, 'ma5': 2400},
            {'buy_amount': 50000000000}
        )

        assert signals['breadth'] == 60
        assert 4 < signals['kospi_trend'] < 5
        assert 50 < signals['foreigner_score'] < 100
        assert signals['decline_ratio'] == 30


class TestEnsembleBreadth:
    def test_ensemble_equal_weights(self):
        """모든 신호가 같은 값일 때 결과는 같아야 함"""
        signals = {
            'breadth': 50,
            'kospi_trend': 0,  # 0~100으로 변환하면 50
            'foreigner_score': 50,
            'decline_ratio': 50
        }
        result = ensemble_breadth(signals)
        assert abs(result - 50) < 0.1

    def test_ensemble_max(self):
        """모든 신호가 최대일 때"""
        signals = {
            'breadth': 100,
            'kospi_trend': 100,  # 0~100으로 변환하면 100
            'foreigner_score': 100,
            'decline_ratio': 100
        }
        result = ensemble_breadth(signals)
        assert result == 100

    def test_ensemble_breadth_dominance(self):
        """breadth가 50% 가중치로 가장 큼"""
        signals1 = {
            'breadth': 100,
            'kospi_trend': 0,
            'foreigner_score': 0,
            'decline_ratio': 0
        }
        signals2 = {
            'breadth': 0,
            'kospi_trend': 100,  # 100
            'foreigner_score': 100,
            'decline_ratio': 100
        }
        result1 = ensemble_breadth(signals1)
        result2 = ensemble_breadth(signals2)

        # breadth=100일 때가 다른 3개가 최대일 때보다 커야 함
        assert result1 > result2

    def test_ensemble_integration_with_collect_signals(self):
        """collect_signals 출력을 앙상블에 직접 사용"""
        signals = collect_signals(
            {'breadth': 60, 'declining': 30, 'rising': 70},
            {'price': 2500, 'ma5': 2400},
            {'buy_amount': 50000000000}
        )
        result = ensemble_breadth(signals)
        # 60(breadth 0.5) + 4.17(kospi 0.2) + 75(foreigner 0.2) + 30(decline 0.1) ≈ 60~70
        assert 55 < result < 75

    def test_ensemble_clips_output(self):
        """앙상블 결과가 0~100 범위로 클립됨"""
        # 모든 값이 0
        signals_zero = {
            'breadth': 0,
            'kospi_trend': -100,
            'foreigner_score': 0,
            'decline_ratio': 0
        }
        result = ensemble_breadth(signals_zero)
        assert result == 0
        assert 0 <= result <= 100
