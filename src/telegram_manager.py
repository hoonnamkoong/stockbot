
import os
import requests
import time

class TelegramManager:
    """
    Centralized manager for Telegram notifications.
    Handles configuration, message formatting, and sending.
    """
    def __init__(self, token=None, chat_id=None):
        self.token = token or os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
        self.chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID', '').strip()
        self.api_base = f"https://api.telegram.org/bot{self.token}/sendMessage"
        
        if not self.token or not self.chat_id:
            print("[TelegramManager] WARNING: Missing Token or Chat ID.")
            
    def send_message(self, text, parse_mode="HTML"):
        """Sends a raw message to Telegram."""
        if not self.token or not self.chat_id:
            print("[TelegramManager] Skipped: No credentials.")
            return False
            
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        
        try:
            response = requests.post(self.api_base, json=payload, timeout=10)
            response.raise_for_status()
            print(f"[TelegramManager] Sent message (len={len(text)}). Status: 200")
            return True
        except Exception as e:
            print(f"[TelegramManager] Error sending message: {e}")
            # Retry without parse_mode if HTML fails
            if parse_mode == "HTML":
                print("[TelegramManager] Retrying as Plain Text...")
                payload.pop('parse_mode', None)
                try:
                    requests.post(self.api_base, json=payload, timeout=10)
                    print("[TelegramManager] Retry successful.")
                    return True
                except Exception as e2:
                    print(f"[TelegramManager] Retry failed: {e2}")
            return False

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
