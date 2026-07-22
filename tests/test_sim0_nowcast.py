import pytest
from src.strategy.simulators.sim0_libero import (
    calculate_kospi_trend, normalize_foreigner_score,
    calculate_decline_ratio, collect_signals, ensemble_breadth,
    score_saturation, score_volatility, score_input_agreement,
    score_timeframe, calculate_confidence
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


class TestScoreSaturation:
    def test_score_saturation_saturation(self):
        """포화 상태 (0점 또는 100점 근처)"""
        assert score_saturation(5.0) == 0.2   # 5점 = 포화
        assert score_saturation(95.0) == 0.2  # 95점 = 포화

    def test_score_saturation_extreme(self):
        """극단값 (포화는 아니지만 극좌표)"""
        assert score_saturation(15.0) == 0.5  # 15점 = 극단
        assert score_saturation(85.0) == 0.5  # 85점 = 극단

    def test_score_saturation_normal(self):
        """정상 범위"""
        assert score_saturation(50.0) == 0.9  # 50점 = 정상
        assert score_saturation(30.0) == 0.9

    def test_score_saturation_boundaries(self):
        """경계값 정확성 (0.1/0.2/0.8/0.9 정규화 경계)"""
        assert score_saturation(10.0) == 0.5  # 정규화 0.1 = 극단 경계
        assert score_saturation(90.0) == 0.5  # 정규화 0.9 = 극단 경계
        assert score_saturation(20.0) == 0.5  # 정규화 0.2 = 극단 경계
        assert score_saturation(80.0) == 0.5  # 정규화 0.8 = 극단 경계

    def test_score_saturation_boundary(self):
        """포화 경계값 정확성 검증 (0.2 / 0.5 / 0.9 경계)"""
        # 정확히 경계값일 때
        assert score_saturation(10.0) == 0.5   # 0.1 정확히 = 0.5(극단)
        assert score_saturation(20.0) == 0.5   # 0.2 정확히 = 0.5(극단)
        assert score_saturation(80.0) == 0.5   # 0.8 정확히 = 0.5(극단)
        assert score_saturation(90.0) == 0.5   # 0.9 정확히 = 0.5(극단)

        # 경계 바로 안쪽
        assert score_saturation(21.0) == 0.9   # 0.21 > 0.2 = 0.9(정상)
        assert score_saturation(79.0) == 0.9   # 0.79 < 0.8 = 0.9(정상)


class TestScoreVolatility:
    def test_score_volatility_high(self):
        """높은 진동 (std > 25)"""
        recent = [{'breadth': 20}, {'breadth': 80}, {'breadth': 30}]
        score = score_volatility(recent)
        assert score == 0.3

    def test_score_volatility_low(self):
        """낮은 진동 (std < 15)"""
        recent = [{'breadth': 50}, {'breadth': 52}, {'breadth': 51}]
        score = score_volatility(recent)
        assert score == 0.9


class TestScoreInputAgreement:
    def test_score_input_agreement_all_bull(self):
        """모든 신호 상승"""
        signals = {
            'breadth': 70,
            'kospi_trend': 20,
            'foreigner_score': 80,
            'decline_ratio': 30
        }
        score = score_input_agreement(signals)
        assert score == 0.9

    def test_score_input_agreement_half(self):
        """50% 일치"""
        signals = {
            'breadth': 70,
            'kospi_trend': 20,
            'foreigner_score': 30,  # < 50 (하락 신호)
            'decline_ratio': 70     # >= 50 (하락 신호)
        }
        score = score_input_agreement(signals)
        assert score == 0.5


class TestScoreTimeframe:
    def test_score_timeframe_progression(self):
        """시간 경과에 따른 증가"""
        assert score_timeframe('09:00') == 0.5
        assert score_timeframe('12:00') == 0.7
        assert score_timeframe('15:00') == 0.9


class TestCalculateConfidence:
    def test_calculate_confidence_normal(self):
        """일반적인 신뢰도 계산"""
        signals = {
            'breadth': 50,
            'kospi_trend': 0,
            'foreigner_score': 50,
            'decline_ratio': 50
        }
        recent = [{'breadth': 50}]
        conf = calculate_confidence(50, recent, '12:00', signals)

        # sat=0.9, vol=0.9(데이터부족), agreement=0.7(decline_ratio=50은 상승신호 아님 → 3개일치),
        # timeframe=0.7 → 0.9 * (0.6 + 0.2*0.9 + 0.1*0.7 + 0.1*0.7) = 0.9 * 0.92 = 0.828
        assert 0.8 < conf <= 1.0

    def test_calculate_confidence_extreme(self):
        """극단 포화 + 높은 진동 → 신뢰도 낮음"""
        recent = [{'breadth': 10}, {'breadth': 90}]
        signals = {
            'breadth': 5,
            'kospi_trend': -50,
            'foreigner_score': 10,
            'decline_ratio': 80
        }
        conf = calculate_confidence(5, recent, '09:00', signals)
        # sat=0.2(포화) * (0.6 + ...) ≤ 0.2 * 1.0 = 0.2
        assert conf < 0.4
