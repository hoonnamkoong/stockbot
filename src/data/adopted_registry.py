"""당일 채택 종목 레지스트리.

한 번 임계값을 넘겨 채택된 종목은 거래량 상위에서 빠지거나 임계값이 올라
미달이 되어도 그날 안에는 계속 추적한다. 그 이력을 날짜 단위로 보관한다.

sync_state.json을 쓰지 않는 이유: SyncState.stocks는 종목코드가 키여야 하는데
data_fetcher가 평면 dict를 .update()로 병합해 종목별 저장이 동작하지 않는다.
"""
import json
import os

PATH = 'data/daily_adopted.json'


def load(today_str: str) -> dict:
    """오늘 채택된 종목 {code: info}. 날짜가 다르거나 파일이 없으면 빈 dict."""
    if not os.path.exists(PATH):
        return {}
    try:
        with open(PATH, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return {}
    if raw.get('date') != today_str:
        return {}
    return raw.get('stocks', {})


def save(today_str: str, stocks: dict) -> None:
    os.makedirs('data', exist_ok=True)
    with open(PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': today_str, 'stocks': stocks}, f, ensure_ascii=False, indent=2)
