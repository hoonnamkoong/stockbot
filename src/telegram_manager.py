
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
            
    # 텔레그램 sendMessage 실제 상한은 4096자. HTML 태그·이모지 바이트 오차를
    # 감안해 여유를 둔다. [2026-08-11] 딥다이브가 2→5종목으로 늘면서 한 메시지가
    # 상한을 넘을 수 있게 됐다 — 넘으면 API가 그냥 거부하는데, 기존 코드는
    # 그 실패를 아무도 안 보고 "발송 완료"로 기록했다.
    TELEGRAM_SAFE_LEN = 3900

    def send_message(self, text, parse_mode="HTML"):
        """텔레그램으로 보낸다. 상한을 넘으면 문단(빈 줄) 경계로 나눠 여러
        메시지로 순차 발송한다. 나눠 보낸 것 중 하나라도 실패하면 False를
        돌려준다 — 일부만 갔는데 성공으로 기록되면 나머지가 조용히 사라진다."""
        if not self.token or not self.chat_id:
            print("[TelegramManager] Skipped: No credentials.")
            return False
        if len(text) <= self.TELEGRAM_SAFE_LEN:
            return self._send_single(text, parse_mode)

        chunks = self._split_into_chunks(text, self.TELEGRAM_SAFE_LEN)
        print(f"[TelegramManager] 메시지가 {len(text)}자라 {len(chunks)}개로 나눠 보냅니다.")
        ok = True
        for chunk in chunks:
            if not self._send_single(chunk, parse_mode):
                ok = False
        return ok

    @staticmethod
    def _split_into_chunks(text: str, limit: int) -> list:
        """빈 줄(\\n\\n) 경계로 나눠 각 조각이 limit 이하가 되게 묶는다.
        문단 하나가 그 자체로 limit을 넘는 드문 경우만 강제로 자른다."""
        paragraphs = text.split('\n\n')
        chunks, current = [], ''
        for p in paragraphs:
            candidate = f"{current}\n\n{p}" if current else p
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
                current = ''
            if len(p) > limit:
                for start in range(0, len(p), limit):
                    chunks.append(p[start:start + limit])
            else:
                current = p
        if current:
            chunks.append(current)
        return chunks

    def _send_single(self, text, parse_mode="HTML"):
        """Sends a raw message to Telegram (4096자 이내라고 가정)."""
        # parse_mode=None은 "서식 없이 보낸다"는 뜻이다. 키를 None으로 넣어
        # 보내면 텔레그램이 그걸 서식 지정으로 받아 거부한다 — 아예 뺀다.
        payload = {"chat_id": self.chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode

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
                    retry_res = requests.post(self.api_base, json=payload, timeout=10)
                    # [Fix] raise_for_status 누락 시 401/400 거부도 "성공"으로 보고돼
                    # 호출부의 발송 실패 감지가 무력화된다 (메시지는 안 갔는데 True).
                    retry_res.raise_for_status()
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
