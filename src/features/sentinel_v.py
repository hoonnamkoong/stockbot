                current_price = current_data['price']
                change_rate = safe_float(current_data['change_rate'])
                
                # Update Peak Price
                if current_price > rec['peak_price']:
                    rec['peak_price'] = current_price
                    
                buy_price = rec['recommended_price']
                profit_rate = (current_price - buy_price) / buy_price * 100
                drop_from_peak = (rec['peak_price'] - current_price) / rec['peak_price'] * 100
                
                if profit_rate > rec.get('highest_profit_rate', -99):
                    rec['highest_profit_rate'] = profit_rate
                
                advice = None
                
                # 1. Stop Loss (Trailing Stop)
                if drop_from_peak >= 4.0 and profit_rate > 0:
                    advice = f"📉 [Trailing Stop] 고점 대비 -{drop_from_peak:.1f}% 하락. 이익 실현 권장."
                elif profit_rate < -5.0:
                     advice = f"💧 [Stop Loss] 진입가 대비 -{abs(profit_rate):.1f}% 하락. 손절 검토."
                     
                # 2. Profit Taking (Overheat)
                posts = current_data.get('recent_posts_count', 0)
                if posts >= 800 and change_rate < 29.0:
                    advice = f"🔥 [Overheat] 게시물 폭발({posts}건). 상한가가 아니라면 분할 매도 권장."
                    
                if advice:
                    msg = f"🔔 <b>[Sentinel-V] Advisory Alert</b>\n\nStock: {rec['name']} ({code})\nAdvice: {advice}\nProfit: {profit_rate:.1f}%"
                    self.tg.send_message(msg)
            
            updated_recs[code] = rec
            
        self.save_recommendations(updated_recs)


    def run(self):
        """Main Execution Flow"""
        print("=== Sentinel-V Advisory System Triggered ===")
        
        # 0. Load History for Anti-FOMO
        print("[Sentinel-V] Loading historical data for Anti-FOMO check...")
        working_days = get_recent_working_days(6) 
        snapshots = load_daily_snapshots(working_days[1:]) # Past 5 days
        
        # 1. Fetch Basic Trend List
        trending_stocks = scraper.get_top_trending_stocks('KOSDAQ')
        
        # Enrich Data
        enriched_stocks = []
        for stock in trending_stocks:
            try:
                details = scraper.get_stock_details(stock['code'])
                stock.update(details)
                today_str = datetime.now().strftime('%Y-%m-%d')
                stats = scraper.get_discussion_stats(stock['code'], today_str, {})
                stock.update(stats)
                enriched_stocks.append(stock)
            except Exception as e:
                print(f"Error enriching {stock['name']}: {e}")
                continue
        
        # 2. Monitor Recommendations
        self.monitor_recommendations(enriched_stocks)
        
        # 3. New Opportunities
        action_taken = False
        recs = self.load_recommendations()
        
        for stock in enriched_stocks[:20]: 
            code = stock['code']
            if code in recs: continue 
            
            # Analyze with Snapshots
            signal, reason = self.analyze_stock(stock, snapshots)
            
            print(f"[{stock['name']}] Signal: {signal} | {reason}")
            
            if signal == "BUY_STRONG":
                action_taken = True
                
                recs[code] = {
                    "name": stock['name'],
                    "recommended_date": datetime.now().strftime('%Y-%m-%d'),
                    "recommended_price": stock['price'],
                    "peak_price": stock['price'],
                    "highest_profit_rate": 0.0,
                    "status": "WATCHING"
