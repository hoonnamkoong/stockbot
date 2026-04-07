import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
import os
import json

folder_path = r'C:\Users\Hoon_DT\gemini\stock\scraping data'

print("Loading data for simulation...")
df = pd.read_csv(os.path.join(folder_path, 'combined_scraping_data.csv'))

# Clean and Prep
column_map = {'현재가': 'price', '등락률': 'change_rate', '현재_외국인비중': 'foreign_rate', '당일_게시글수': 'recent_posts_count'}
df = df.rename(columns=column_map)
df = df.dropna(subset=['price', 'change_rate'])

def clean_numeric(val):
    if pd.isna(val): return 0.0
    val_str = str(val).replace(',', '').replace('%', '').strip()
    try: return float(val_str)
    except: return 0.0

df['change_rate_num'] = df['change_rate'].apply(clean_numeric)
df['foreign_rate_num'] = df['foreign_rate'].apply(clean_numeric)
df['price_num'] = df['price'].apply(clean_numeric)
df['recent_posts'] = df['recent_posts_count'].apply(lambda x: int(clean_numeric(x)))

def calculate_relative_hype(row):
    posts = row['recent_posts']
    hour = 15 
    if '취합시간' in row and pd.notna(row['취합시간']):
        try:
            time_str = str(row['취합시간'])
            if ':' in time_str: hour = int(time_str.split(':')[0])
        except: pass
    if 9 <= hour < 12: threshold = 40
    elif 12 <= hour < 14: threshold = 60
    elif 14 <= hour < 24: threshold = 100
    else: threshold = 10
    return min(posts / threshold, 10.0)
    
df['relative_hype'] = df.apply(calculate_relative_hype, axis=1)

df['date_dt'] = pd.to_datetime(df['date'], errors='coerce')
df = df.sort_values(by=['code', 'date_dt'])
df['next_day_change'] = df.groupby('code')['change_rate_num'].shift(-1)
df['next_day_price'] = df.groupby('code')['price_num'].shift(-1)

# Train ML Model on all data for simplicity of the simulator, or train on first 70% and test on last 30% dates
dates = sorted(df['date_dt'].dropna().unique())
split_idx = int(len(dates) * 0.7)
train_dates = dates[:split_idx]
test_dates = dates[split_idx:]

train_df = df[df['date_dt'].isin(train_dates)].copy()
test_df = df[df['date_dt'].isin(test_dates)].copy()

train_df = train_df.dropna(subset=['next_day_change'])
train_df['target'] = (train_df['next_day_change'] > 0).astype(int)

X_train = train_df[['change_rate_num', 'foreign_rate_num', 'relative_hype']]
y_train = train_df['target']

print("Training ML model...")
model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
model.fit(X_train, y_train)

# Portfolio Setup
INITIAL_CASH = 3000000
MAX_ALLOCATION_PER_STOCK = 0.20 # 20% max per stock
FEE_BUY = 0.00015
FEE_SELL = 0.00215 # 0.015% fee + 0.2% tax

cash = INITIAL_CASH
holdings = {} # code: {qty, avg_price, buy_date, days_held}
trade_log = []

# To simulate chronological flow, we need a price dictionary for O(1) lookups
price_history = {} # code -> {date -> price, date -> change_rate}
for _, row in test_df.iterrows():
    c = row['code']
    d = row['date_dt'].strftime('%Y-%m-%d')
    if c not in price_history: price_history[c] = {}
    price_history[c][d] = {'price': row['price_num'], 'change': row['change_rate_num'], 'feature_row': row}

date_str_list = [d.strftime('%Y-%m-%d') for d in test_dates]

print(f"Starting chronological simulation across {len(test_dates)} trading days...")
for current_date in date_str_list:
    # 1. Update Holdings & Check SL/TP
    codes_to_sell = []
    
    # Needs current price to evaluate SL/TP. If not traded today, assume same.
    # We will just look if the stock is in price_history for today
    for code, h in holdings.items():
        if code in price_history and current_date in price_history[code]:
            current_price = price_history[code][current_date]['price']
            h['days_held'] += 1
            
            profit_rate = ((current_price - h['avg_price']) / h['avg_price']) * 100
            
            # Predict fresh ML prob if it's in the scrape today
            ml_prob = 50.0
            row_today = price_history[code][current_date]['feature_row']
            X_eval = pd.DataFrame([row_today[['change_rate_num', 'foreign_rate_num', 'relative_hype']]])
            ml_prob = model.predict_proba(X_eval)[0][1] * 100
            
            # Action Logic
            sell_reason = None
            if profit_rate >= 10.0 and ml_prob < 50.0:
                sell_reason = f"TP (+{profit_rate:.1f}%) & Momentum Dropped"
            elif profit_rate >= 20.0:
                sell_reason = f"Max TP (+{profit_rate:.1f}%)"
            elif profit_rate <= -7.0:
                sell_reason = f"Stop Loss ({profit_rate:.1f}%)"
            elif h['days_held'] >= 10:
                sell_reason = f"Time Stop (10 Days)"
                
            if sell_reason:
                # Execute Sell
                sell_vol = current_price * h['qty']
                fee = sell_vol * FEE_SELL
                net_return = sell_vol - fee
                cash += net_return
                trade_log.append({
                    'date': current_date, 'type': 'SELL', 'code': code, 
                    'qty': h['qty'], 'price': current_price, 'profit_rate': profit_rate, 'reason': sell_reason
                })
                codes_to_sell.append(code)
                
    for c in codes_to_sell:
        del holdings[c]
        
    # 2. Buy new stocks
    today_pool = test_df[test_df['date_dt'].dt.strftime('%Y-%m-%d') == current_date].copy()
    if len(today_pool) > 0:
        X_today = today_pool[['change_rate_num', 'foreign_rate_num', 'relative_hype']]
        today_pool['ml_prob'] = model.predict_proba(X_today)[:, 1] * 100
        
        # Filter high probabilities
        buys = today_pool[today_pool['ml_prob'] >= 60.0].sort_values(by='ml_prob', ascending=False)
        
        for _, buy_row in buys.iterrows():
            code = buy_row['code']
            if code in holdings: continue # Don't buy if already holding
            
            # Position sizing
            max_alloc = INITIAL_CASH * MAX_ALLOCATION_PER_STOCK # 600,000 KRW
            alloc = min(max_alloc, cash)
            price = buy_row['price_num']
            
            if price <= 0: continue
            
            qty = int(alloc // price)
            if qty > 0:
                buy_vol = qty * price
                fee = buy_vol * FEE_BUY
                total_cost = buy_vol + fee
                
                if cash >= total_cost:
                    cash -= total_cost
                    holdings[code] = {
                        'qty': qty, 'avg_price': price, 'buy_date': current_date, 'days_held': 0, 'name': buy_row.get('종목명', code)
                    }
                    trade_log.append({
                        'date': current_date, 'type': 'BUY', 'code': code, 'name': buy_row.get('종목명', code),
                        'qty': qty, 'price': price, 'prob': buy_row['ml_prob']
                    })

# Final Evaluation
total_asset = cash
unrealized_profit = 0
for code, h in holdings.items():
    # Use last known price
    last_price = h['avg_price']
    d_idx = date_str_list[-1]
    if code in price_history and d_idx in price_history[code]:
        last_price = price_history[code][d_idx]['price']
    
    val = h['qty'] * last_price
    total_asset += val
    unrealized_profit += val - (h['qty'] * h['avg_price'])

total_profit_rate = ((total_asset - INITIAL_CASH) / INITIAL_CASH) * 100

print("\n=== 📈 SIMULATION RESULTS ===")
print(f"Total Trading Days: {len(test_dates)}")
print(f"Initial Cash: {INITIAL_CASH:,.0f} KRW")
print(f"Final Total Asset: {total_asset:,.0f} KRW")
print(f"Final Total Cash: {cash:,.0f} KRW")
print(f"Net Profit: {total_asset - INITIAL_CASH:,.0f} KRW ({total_profit_rate:+.2f}%)")
print(f"Total Trades: {len(trade_log)}")

# Calculate Win Rate from closed SELL trades
sells = [t for t in trade_log if t['type'] == 'SELL']
if sells:
    wins = len([s for s in sells if s['profit_rate'] > 0])
    win_rate = (wins / len(sells)) * 100
    print(f"Trade Win Rate: {win_rate:.1f}% ({wins} wins / {len(sells)-wins} losses)")

print("\nLast 5 Trades:")
for t in trade_log[-5:]:
    if t['type'] == 'BUY':
        print(f"[{t['date']}] BUY {t['name']} ({t['qty']} shares @ {t['price']:,.0f}) - ML Prob: {t['prob']:.1f}%")
    else:
        print(f"[{t['date']}] SELL {t['code']} ({t['qty']} shares @ {t['price']:,.0f}) - Profit: {t['profit_rate']:+.2f}% ({t['reason']})")

with open('simulation_output.txt', 'w', encoding='utf-8') as f:
    f.write(f"Final Balance: {total_asset:,.0f} KRW\nProfit: {total_profit_rate:+.2f}%\nWin Rate: {win_rate if sells else 0:.1f}%\n")
