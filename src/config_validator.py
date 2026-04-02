"""
[Grand Protocol] Config Validator
==================================
환경 변수 누락 방어 모듈입니다.
- 시크릿 값 자체(토큰, 키)는 절대 로그에 출력하지 않습니다.
- 변수명(키 이름)과 누락 여부만 출력합니다.
"""
import os
import re


# ─── 마스킹 유틸리티 ─────────────────────────────────────────────────────────

def mask_sensitive(text: str) -> str:
    """
    40자 이상의 영숫자 연속 문자열(토큰/API 키)을 자동 마스킹합니다.
    앞 4자만 표시하고 나머지는 '***'으로 치환합니다.
    """
    return re.sub(
        r'([A-Za-z0-9_\-]{40,})',
        lambda m: m.group(0)[:4] + '***',
        text
    )


# ─── 필수 환경 변수 정의 ──────────────────────────────────────────────────────

# scraper.py 실행에 필요한 시크릿
SCRAPER_REQUIRED = {
    'TELEGRAM_BOT_TOKEN': '텔레그램 봇 토큰',
    'TELEGRAM_CHAT_ID':   '텔레그램 채팅 ID',
    'GOOGLE_API_KEY':     'Google Gemini API 키 (GEMINI_KEY 대체)',
}

# trade_executor.py / KIS API 에 필요한 시크릿
TRADE_REQUIRED = {
    'DASHBOARD_URL': 'Vercel API Base URL (프록시 용)',
    'TRADE_PIN':     'Vercel API 매매 승인 핀 번호',
}


# ─── 검증 함수 ───────────────────────────────────────────────────────────────

def validate(required_keys: dict, context: str = "") -> tuple:
    """
    필수 환경 변수 목록을 검증합니다.

    Args:
        required_keys (dict): { 'ENV_VAR_NAME': '설명' } 형태의 딕셔너리
        context (str): 로그 출력 시 어떤 모듈에서 검증하는지 표시

    Returns:
        (is_ok: bool, missing_descriptions: list[str])
        - is_ok: 모든 키가 존재하면 True
        - missing_descriptions: 누락된 키의 설명(이름 포함) 리스트
          [중요] 키의 실제 값(토큰 문자열)은 절대 포함되지 않습니다.
    """
    missing = []
    label = f"[ConfigValidator:{context}]" if context else "[ConfigValidator]"

    for key, desc in required_keys.items():
        val = os.environ.get(key, '').strip()
        if not val:
            missing.append(f"누락: {desc} (변수명={key})")
            print(f"{label} ⚠️  환경 변수 누락 — {desc} (변수명={key})")
            continue

        # ─── 값 유효성 검증 (Validation) ───
        is_val_ok = True
        error_detail = ""

        # 1. 텔레그램 토큰 (최소 40자 이상 예상)
        if key == 'TELEGRAM_BOT_TOKEN' and len(val) < 40:
            is_val_ok = False
            error_detail = f"토큰 길이가 너무 짧음 (현재 {len(val)}자)"

        # 2. 계좌번호 (숫자 10자리)
        elif key == 'KIS_ACCOUNT_NO':
            clean_acc = val.replace('-', '')
            if not clean_acc.isdigit():
                is_val_ok = False
                error_detail = "계좌번호에 숫자가 아닌 문자가 포함됨"
            elif len(clean_acc) < 10:
                is_val_ok = False
                error_detail = f"계좌번호 길이가 너무 짧음 (현재 {len(clean_acc)}자, 10자 필요)"

        # 3. API 키 (Gemini/Google)
        elif key in ['GOOGLE_API_KEY', 'GEMINI_KEY'] and len(val) < 30:
            is_val_ok = False
            error_detail = "API 키 형식이 올바르지 않음 (너무 짧음)"

        if not is_val_ok:
            missing.append(f"유효성 실패: {desc} ({error_detail})")
            print(f"{label} ❌ {desc} 유효성 검증 실패: {error_detail}")
        else:
            # 값이 있고 유효함 (실제 값은 마스킹하여 표시)
            print(f"{label} ✅ {desc} (변수명={key}, 길이={len(val)}자)")

    is_ok = len(missing) == 0
    if is_ok:
        print(f"{label} 모든 환경 변수 검증 통과.")
    else:
        print(f"{label} ❌ {len(missing)}개 항목 오류(누락 또는 유효성 실패).")

    return is_ok, missing


def validate_scraper() -> tuple:
    """스크래퍼 필수 환경 변수를 검증합니다."""
    # GOOGLE_API_KEY / GEMINI_KEY 둘 중 하나만 있어도 OK
    effective = dict(SCRAPER_REQUIRED)
    if os.environ.get('GEMINI_KEY', '').strip():
        # GEMINI_KEY가 있으면 GOOGLE_API_KEY 검증을 건너뜀
        effective.pop('GOOGLE_API_KEY', None)
    return validate(effective, context="Scraper")


def validate_trade() -> tuple:
    """KIS 트레이딩 필수 환경 변수를 검증합니다."""
    return validate(TRADE_REQUIRED, context="Trade")
