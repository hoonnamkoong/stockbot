
import os
import pandas as pd
import glob
from src.telegram_manager import TelegramManager

def dry_run_verification():
    print("[DryRun] Starting Verification...")
    
    # 1. Find latest CSV
    list_of_files = glob.glob('trending_integrated_*.csv') 
    if not list_of_files:
        print("[DryRun] No CSV files found to verify.")
        return

    latest_file = max(list_of_files, key=os.path.getctime)
    print(f"[DryRun] Loading data from: {latest_file}")
    
    try:
        df = pd.read_csv(latest_file)
        records = df.to_dict('records')
        
        # 2. Setup Manager with Mock Send
        manager = TelegramManager(token="MOCK", chat_id="MOCK")
        
        # 3. Process KOSPI
        kospi_items = [r for r in records if r.get('시장구분') == 'KOSPI']
        if kospi_items:
            print("\n--- [KOSPI Message Preview] ---")
            # We treat send_message as print here
            # Copy-paste logic from send_market_report to see output
            sorted_stocks = sorted(kospi_items, key=lambda x: x.get('당일_게시글수', 0), reverse=True)
            top_stocks = sorted_stocks[:5]
            
            msg = f"📉 <b>[KOSPI] Top 5 (토론 급등) (v7.0)</b>\n\n"
            for stock in top_stocks:
                name = stock.get('종목명', 'Unknown')
                price = stock.get('현재가', 0)
                if isinstance(price, (int, float)):
                    price = f"{price:,}"
                rate = stock.get('등락률', '0%')
                posts = stock.get('당일_게시글수', 0)
                summary = stock.get('게시물_요약', '요약 없음')
                if len(str(summary)) > 80:
                    summary = str(summary)[:80] + "..."
                
                msg += f"🔥 <b>{name}</b> ({price}원 | {rate})\n"
                msg += f"💬 {posts}개 의견\n"
                msg += f"📝 {summary}\n\n"
            
            print(msg)
            print("------------------------------")
            
        # 4. Process KOSDAQ
        kosdaq_items = [r for r in records if r.get('시장구분') == 'KOSDAQ']
        if kosdaq_items:
            print("\n--- [KOSDAQ Message Preview] ---")
            sorted_stocks = sorted(kosdaq_items, key=lambda x: x.get('당일_게시글수', 0), reverse=True)
            top_stocks = sorted_stocks[:5]
            
            msg = f"📉 <b>[KOSDAQ] Top 5 (토론 급등) (v7.0)</b>\n\n"
            for stock in top_stocks:
                name = stock.get('종목명', 'Unknown')
                price = stock.get('현재가', 0)
                if isinstance(price, (int, float)):
                    price = f"{price:,}"
                rate = stock.get('등락률', '0%')
                posts = stock.get('당일_게시글수', 0)
                summary = stock.get('게시물_요약', '요약 없음')
                if len(str(summary)) > 80:
                    summary = str(summary)[:80] + "..."
                
                msg += f"🔥 <b>{name}</b> ({price}원 | {rate})\n"
                msg += f"💬 {posts}개 의견\n"
                msg += f"📝 {summary}\n\n"
            
            print(msg)
            print("------------------------------")

    except Exception as e:
        print(f"[DryRun] Error: {e}")

if __name__ == "__main__":
    dry_run_verification()
