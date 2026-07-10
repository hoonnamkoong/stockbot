"""당일 채택 종목 레지스트리.

한 번 임계값을 넘겨 채택된 종목은 거래량 상위에서 빠지거나 임계값이 올라
미달이 되어도 그날 안에는 계속 추적한다. 그 이력을 날짜 단위로 보관한다.

sync_state.json에 얹지 않는 이유: 그쪽은 텔레그램 중복 방지·매매 세션 상태를 담는
파일이다. AI 요약 텍스트를 섞으면 매매 상태 파일이 대시보드 캐시를 겸하게 된다.
"""
import json
import os
import tempfile

PATH = 'data/daily_adopted.json'


def load(today_str: str) -> dict:
    """오늘 채택된 종목 {code: info}. 날짜가 다르거나 파일이 없으면 빈 dict."""
    if not os.path.exists(PATH):
        return {}
    try:
        with open(PATH, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        # JSON이 dict가 아니거나 다른 타입이면 AttributeError 발생 방지
        if raw.get('date') != today_str:
            return {}
        return raw.get('stocks', {})
    except Exception:
        return {}


def save(today_str: str, stocks: dict) -> None:
    """임시 파일에 쓴 뒤 원자적으로 교체한다.

    직접 덮어쓰면 쓰기 도중 죽었을 때 반쪽 JSON이 남고, load()가 그것을 버려
    당일 채택 이력과 AI 캐시가 통째로 사라진다.
    """
    os.makedirs('data', exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir='data', prefix='.daily_adopted-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'date': today_str, 'stocks': stocks}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PATH)
    except BaseException:
        os.unlink(tmp)
        raise
