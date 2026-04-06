"""
[Grand Protocol] NotificationService
======================================
알림 전송의 유일한 진입점(Single Entry Point) 모듈입니다.

설계 원칙:
- scraper.py 는 이 클래스만 호출합니다. TelegramManager를 직접 임포트하지 않습니다.
- 메시지 전송은 각각 독립된 try-except 블록으로 격리합니다.
  → 하나가 실패해도 나머지 메시지는 계속 전송됩니다.
- 이 모듈에서 발생한 에러는 scraper.py 의 스크래핑 로직에 영향을 주지 않습니다.
- 시크릿 값은 로그에 출력하지 않습니다.
"""
import os
import sys
import traceback

# telegram_manager는 이 모듈 내부에서만 사용합니다.
try:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from telegram_manager import TelegramManager
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False


# ─── 내부 헬퍼 ───────────────────────────────────────────────────────────────

def _audible_send(tg: 'TelegramManager', message: str, label: str = "") -> bool:
    """
    단일 메시지를 전송하며, 실패 시 상세 Traceback을 로그에 남깁니다 (Silent Failure 방지).
    """
    try:
        # [DEBUG] 전송 시도 로깅 (마스킹 적용)
        from src.config_validator import mask_sensitive
        preview = message[:50].replace('\n', ' ') + "..."
        print(f"[NotificationService] >>> 전송 시도 ({label}): {preview}")
        
        result = tg.send_message(message)
        
        if result:
            print(f"[NotificationService] ✅ 전송 성공: {label}")
        else:
            # TelegramManager.send_message가 False를 반환하는 경우 (내부적으로 catch된 경우)
            print(f"[NotificationService] ⚠️  전송 실패(응답 False): {label}")
        return result
    except Exception as e:
        print(f"\n[NotificationService] ❌ [CRITICAL ERROR] {label} 전송 중 예외 발생!")
        print("-" * 60)
        traceback.print_exc() # GitHub Actions 로그에 상세 에러 박제
        print("-" * 60)
        return False


# ─── 메인 클래스 ─────────────────────────────────────────────────────────────

class NotificationService:
    """
    텔레그램 알림 전송의 유일한 진입점.
    """

    def __init__(self):
        self._tg = None
        self._available = False
        self._init_telegram()

    def _init_telegram(self):
        """TelegramManager를 초기화합니다."""
        if not _TG_AVAILABLE:
            print("[NotificationService] ⚠️  TelegramManager 임포트 실패. 알림 비활성화.")
            return

        # [Standard] Gemini API 키 유연성 확보 (GOOGLE_API_KEY 또는 GEMINI_KEY 지원)
        gemini_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_KEY', '').strip()
        token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
        chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()

        # [DEBUG] 초기화 시점의 환경 변수 상태 확인 (마스킹)
        from src.config_validator import mask_sensitive
        print(f"[NotificationService] 초기화 시도: Token={mask_sensitive(token)}, ChatID={chat_id[:4]}***, GeminiKey={mask_sensitive(gemini_key)}")

        if not token or not chat_id:
            print("[NotificationService] ⚠️  필수 환경 변수(TOKEN/CHAT_ID) 누락.")
            return

        try:
            self._tg = TelegramManager()
            self._available = True
            print("[NotificationService] ✅ TelegramManager 초기화 성공.")
        except Exception as e:
            print(f"[NotificationService] ❌ TelegramManager 생성 실패!")
            traceback.print_exc()

    @property
    def is_available(self) -> bool:
        return self._available and self._tg is not None

    # ─── 공개 메서드 ───────────────────────────────────────────────────────────

    def send_hourly_report(
        self,
        kospi_records: list,
        kosdaq_records: list,
        advisor_report_text: str = "",
        dashboard_url: str = "",
    ) -> bool:
        """
        정시 리포트를 전송합니다. 하나라도 실패하면 False를 반환하여 상위에 알립니다.
        """
        if not self.is_available:
            print("[NotificationService] 알림 비활성화 상태 — 전송 건너뜀.")
            return False

        all_success = True

        # 1. KOSPI 리포트
        if kospi_records:
            try:
                msg = self._build_market_report("KOSPI", kospi_records)
                if not _audible_send(self._tg, msg, label="KOSPI 리포트"):
                    all_success = False
            except Exception:
                traceback.print_exc()
                all_success = False

        # 2. KOSDAQ 리포트
        if kosdaq_records:
            try:
                msg = self._build_market_report("KOSDAQ", kosdaq_records)
                if not _audible_send(self._tg, msg, label="KOSDAQ 리포트"):
                    all_success = False
            except Exception:
                traceback.print_exc()
                all_success = False

        # 3. 전략 가이드
        if advisor_report_text:
            try:
                MAX_LEN = 3500
                if len(advisor_report_text) > MAX_LEN:
                    parts = [advisor_report_text[i:i + MAX_LEN] for i in range(0, len(advisor_report_text), MAX_LEN)]
                    for idx, part in enumerate(parts):
                        if not _audible_send(self._tg, f"🧠 <b>[Strategic Guide {idx + 1}/{len(parts)}]</b>\n{part}", label=f"전력 가이드 {idx+1}"):
                            all_success = False
                else:
                    if not _audible_send(self._tg, f"🧠 <b>[Strategic Guide]</b>\n{advisor_report_text}", label="전략 가이드"):
                        all_success = False
            except Exception:
                traceback.print_exc()
                all_success = False

        # 4. 대시보드 링크
        try:
            url = dashboard_url or os.environ.get('DASHBOARD_URL', 'https://stockbot-phi.vercel.app')
            if not _audible_send(self._tg, f"👉 <b>Dashboard</b>: {url}", label="대시보드 링크"):
                # 링크 전송 실패는 리포트 성공 여부에 치명적이지 않을 수 있으나 일단 기록
                pass
        except Exception:
            traceback.print_exc()

        return all_success

    def send_no_data_alert(self, threshold: int) -> bool:
        if not self.is_available: return False
        try:
            import time
            msg = f"📉 <b>[Report] {time.strftime('%H:%M')}</b>\nThreshold: {threshold} posts\nℹ️ 조건 합치 종목 없음."
            return _audible_send(self._tg, msg, label="데이터 없음 알림")
        except Exception:
            traceback.print_exc()
            return False

    def send_error_alert(self, error_msg: str) -> None:
        if not self.is_available: return
        try:
            from src.config_validator import mask_sensitive
            safe_msg = mask_sensitive(str(error_msg))
            _audible_send(self._tg, f"⚠️ <b>[System Error]</b>\n{safe_msg}", label="에러 알림")
        except Exception:
            traceback.print_exc()

    # ─── 내부 빌더 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_market_report(market: str, records: list) -> str:
        """
        market: 'KOSPI' or 'KOSDAQ'
        records: result_df_kr.to_dict('records') 결과 리스트
        """
        icon = "📉" if market == "KOSPI" else "📈"
        if records:
            top5 = records[:5]
            for item in top5:
                name = item.get('종목명', item.get('name', '?'))
                try:
                    price = f"{int(item.get('현재가', item.get('price', 0))):,}"
                except (ValueError, TypeError):
                    price = str(item.get('현재가', item.get('price', '?')))

                change = item.get('등락률', item.get('change_rate', '?'))
                posts = item.get('당일_게시글수', item.get('recent_posts_count', '?'))
                summary = item.get('게시물_요약', item.get('posts_summary', '요약 없음'))

                if isinstance(summary, str) and len(summary) > 100:
                    summary = summary[:100] + "..."

                msg += f"🔥 <b>{name}</b> ({price}원 | {change})\n"
                msg += f"💬 {posts}개 의견\n"
                msg += f"📝 {summary}\n\n"
        else:
            msg += "⚠️ 현재 기준을 충족하는 종목이 없습니다.\n\n"

        if len(records) > 5:
            msg += f"<i>... 외 {len(records) - 5}개 종목 — Dashboard 확인</i>\n"

        return msg
