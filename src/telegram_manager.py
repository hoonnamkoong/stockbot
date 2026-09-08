
import os
import time

from src.core import notify


class TelegramManager:
    """리포트 메시지를 **조립**한다. 보내는 일은 src.core.notify가 한다.

    [2026-09-08] 발신 코어(분할·재시도·HTTP)를 notify로 옮겼다. 예전에는 이
    클래스와 notify_workflow_failure.py·audit_data_freshness.py 셋이 각자
    보냈고, 4096자 분할과 평문 폴백이 **여기에만** 있었다 — 나머지 둘의 긴
    메시지는 텔레그램이 그냥 거부했고 아무도 몰랐다.

    도메인 조립(무엇을 어떤 문장으로 쓰는가)은 여기 남는다. notify는 텍스트만 안다.
    """
    def __init__(self, token=None, chat_id=None):
        self.token = token or os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID', '').strip()

        if not self.token or not self.chat_id:
            print("[TelegramManager] WARNING: Missing Token or Chat ID.")
            
    # 상한·분할·재시도는 전부 src.core.notify가 갖는다. 여기 사본을 두면
    # 또 갈라진다 — 그게 이 리팩터링의 이유다.
    TELEGRAM_SAFE_LEN = notify.SAFE_LEN

    def send_message(self, text, parse_mode="HTML"):
        """텔레그램으로 보낸다. 하나라도 실패하면 False."""
        return notify.send(text, parse_mode=parse_mode,
                           token=self.token, chat_id=self.chat_id)

    def send_dashboard_link(self):
        """Sends the Dashboard Link (Always First)."""
        # Hardcoded fallback as requested in V6.9
        dashboard_url = os.environ.get('DASHBOARD_URL', 'https://stockbot-phi.vercel.app/')
        msg = f"📊 <b>Dashboard Check (v7.0)</b>\n<a href='{dashboard_url}'>{dashboard_url}</a>"
        return self.send_message(msg)

    def send_market_report(self, market_name, stock_data_list):
        """
        Formats and sends the report for a specific market (KOSPI/KOSDAQ).
        Expects a list of dicts with keys: '종목명', '현재가', '등락률', '당일_게시글수', '게시물_요약'
        """
        if not stock_data_list:
            return False
            
        # Sorting just in case
        sorted_stocks = sorted(stock_data_list, key=lambda x: x.get('당일_게시글수', x.get('recent_posts_count', 0)), reverse=True)
        top_stocks = sorted_stocks[:5]
        
        msg = f"📉 <b>[{market_name}] Top 5 (토론 급등) (v7.0)</b>\n\n"
        
        for stock in top_stocks:
            name = stock.get('종목명', stock.get('name', 'Unknown'))
            price = stock.get('현재가', stock.get('price', 0))
            if isinstance(price, (int, float)):
                price = f"{price:,}"
            rate = stock.get('등락률', stock.get('change_rate', '0%'))
            posts = stock.get('당일_게시글수', stock.get('recent_posts_count', 0))
            summary = stock.get('게시물_요약', stock.get('posts_summary', '요약 없음'))
            
            # Truncate summary to 80 chars
            if len(summary) > 80:
                summary = summary[:80] + "..."
                
            msg += f"🔥 <b>{name}</b> ({price}원 | {rate})\n"
            msg += f"💬 {posts}개 의견\n"
            msg += f"📝 {summary}\n\n"
            
        return self.send_message(msg)

    def send_no_data_alert(self, threshold):
        """Sends an alert if no stocks met the criteria."""
        timestamp = time.strftime('%H:%M')
        msg = (
            f"📉 <b>[Report] {timestamp}</b>\n"
            f"Threshold: {threshold} posts\n"
            f"ℹ️ 조건에 맞는 급상승 종목이 없습니다. (No stocks found)"
        )
        return self.send_message(msg)
