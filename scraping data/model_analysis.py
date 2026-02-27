import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
import os

folder_path = r'C:\Users\Hoon_DT\gemini\stock\scraping data'
file_path = os.path.join(folder_path, 'combined_scraping_data.csv')

print(f"Loading data from {file_path}...")
df = pd.read_csv(file_path)

# Map Korean columns to English for the script
column_map = {
    '현재가': 'price',
    '등락률': 'change_rate',
    '현재_외국인비중': 'foreign_rate',
    '당일_게시글수': 'recent_posts_count'
}
df = df.rename(columns=column_map)
df = df.dropna(subset=['price', 'change_rate'])

def clean_numeric(val):
    if pd.isna(val): return 0.0
    val_str = str(val).replace(',', '').replace('%', '').strip()
    try:
        return float(val_str)
    except:
        return 0.0

# Apply cleaning BEFORE splitting
df['change_rate_num'] = df['change_rate'].apply(clean_numeric)
df['foreign_rate_num'] = df['foreign_rate'].apply(clean_numeric)
df['recent_posts'] = df['recent_posts_count'].apply(lambda x: int(clean_numeric(x)))

# --- 1. Data Splitting (70% Train, 30% Test) ---
train_df, test_df = train_test_split(df, test_size=0.3, random_state=42)
print(f"Modeling Data: {len(train_df)} rows")
print(f"Testing Data: {len(test_df)} rows")

# --- 2. Current Algorithm Backtest on Test Data ---
def apply_sentinel(row):
    p_change = row['change_rate_num']
    frg = row['foreign_rate_num']
    rec_posts = row['recent_posts']
    
    trend_score = 0
    if p_change > 2.0: trend_score += 20
    if p_change > 5.0: trend_score += 10
    if p_change > 15.0: trend_score += 10
    
    supply_score = 0
    if frg > 0: supply_score += 10
    if frg > 5: supply_score += 10
    
    buzz_score = 0
    if rec_posts > 50: buzz_score += 10
    if rec_posts > 100: buzz_score += 10
    
    total_score = trend_score + supply_score + buzz_score
    
    if total_score >= 60: return "BUY_STRONG"
    elif total_score >= 40: return "BUY"
    elif p_change < -3.0: return "SELL"
    else: return "HOLD"

print("\nRunning current SentinelV algorithm on Test Data...")
test_df = test_df.copy()
test_df['signal'] = test_df.apply(apply_sentinel, axis=1)

buy_signals = test_df[test_df['signal'].isin(['BUY_STRONG', 'BUY'])]
print(f"Algorithm triggered {len(buy_signals)} BUY signals out of {len(test_df)} cases ({(len(buy_signals)/len(test_df))*100:.1f}%)")

if len(buy_signals) > 0:
    print(f"Average current Change Rate of BUY selection: {buy_signals['change_rate_num'].mean():.2f}%")
    print(f"Average Buzz of BUY selection: {buy_signals['recent_posts'].mean():.2f} posts")

# Simulate T+1 data to calculate Return
df['date_dt'] = pd.to_datetime(df['date'], errors='coerce')
df = df.sort_values(by=['code', 'date_dt'])
df['next_day_change'] = df.groupby('code')['change_rate_num'].shift(-1)

# Re-split with target variable for return analysis
print("\nRe-evaluating with T+1 Data (next day's change rate)...")
valid_df = df.dropna(subset=['next_day_change']).copy()
train_v, test_v = train_test_split(valid_df, test_size=0.3, random_state=42)

test_v['signal'] = test_v.apply(apply_sentinel, axis=1)
valid_buys = test_v[test_v['signal'].isin(['BUY_STRONG', 'BUY'])]

avg_next_day = 0
win_rate = 0
if len(valid_buys) > 0:
    avg_next_day = valid_buys['next_day_change'].mean()
    win_rate = (valid_buys['next_day_change'] > 0).mean() * 100
    print(f"--- EXPECTED RETURN ANALYSIS ---")
    print(f"Average Return (T+1) if bought: {avg_next_day:.2f}%")
    print(f"Win Rate (T+1 positive): {win_rate:.1f}%")
    
    hold_cases = test_v[test_v['signal'] == 'HOLD']
    if len(hold_cases) > 0:
        print(f"Baseline Return (if Hold/Random): {hold_cases['next_day_change'].mean():.2f}%")

# Save split datasets
train_v.to_csv(os.path.join(folder_path, 'model_train_data.csv'), index=False, encoding='utf-8-sig')
test_v.to_csv(os.path.join(folder_path, 'model_test_data.csv'), index=False, encoding='utf-8-sig')

print("\n--- 3. IMPROVEMENT OPTIONS ANALYZER ---")
print("Analyzing Train data to find better factors...")
corr = train_v[['change_rate_num', 'foreign_rate_num', 'recent_posts', 'next_day_change']].corr()['next_day_change']
print("\nCorrelation with Next Day Return:")
print(corr)

with open(os.path.join(folder_path, 'analysis_report.txt'), 'w', encoding='utf-8') as f:
    f.write(f"Test Data Buy Return: {avg_next_day:.2f}%\n")
    f.write(f"Test Data Win Rate: {win_rate:.1f}%\n")
    f.write(f"Correlations:\n{corr.to_string()}\n")
