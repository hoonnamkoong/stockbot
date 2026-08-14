"""요율은 fees.py에만 산다. 원장에 싣는 이유는 TS가 복사하지 않게 하려는 것이다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import stamp_fee_rates
from src.trade import fees


def test_stamps_the_rates_from_the_single_definition():
    led = {}
    stamp_fee_rates(led)
    assert led['fee_rates'] == {
        'buy': fees.BUY_FEE_RATE,
        'sell': fees.SELL_FEE_RATE,
        'tax': fees.SELL_TAX_RATE,
    }


def test_stamping_twice_is_idempotent():
    led = {}
    stamp_fee_rates(led)
    first = dict(led['fee_rates'])
    stamp_fee_rates(led)
    assert led['fee_rates'] == first
