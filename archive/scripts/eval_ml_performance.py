import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
import os

folder_path = r'C:\Users\Hoon_DT\gemini\stock\scraping data'

# Load pre-split data
train_df = pd.read_csv(os.path.join(folder_path, 'model_train_data.csv'))
test_df = pd.read_csv(os.path.join(folder_path, 'model_test_data.csv'))

# 1. Feature Engineering: Relative Hype
for df in [train_df, test_df]:
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

# 2. Train Model
train_df['target'] = (train_df['next_day_change'] > 0).astype(int)
X_train = train_df[['change_rate_num', 'foreign_rate_num', 'relative_hype']]
y_train = train_df['target']

model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
model.fit(X_train, y_train)

# 3. Evaluate on Test Data
X_test = test_df[['change_rate_num', 'foreign_rate_num', 'relative_hype']]
test_df['ml_prob'] = model.predict_proba(X_test)[:, 1] * 100

# Original SentinelV Logic (re-run to compare exact same subset)
def apply_sentinel(row):
    p_change = row['change_rate_num']
    frg = row['foreign_rate_num']
    rec_posts = row['recent_posts']
    t = trend_score = supply_score = buzz_score = 0
    if p_change > 2.0: trend_score += 20
    if p_change > 5.0: trend_score += 10
    if p_change > 15.0: trend_score += 10
    if frg > 0: supply_score += 10
    if frg > 5: supply_score += 10
    
    # SentinelV dynamic threshold based on extracted hour (simplified for fallback)
    # Using raw posts for old logic as we did earlier
    if rec_posts > 50: buzz_score += 10
    if rec_posts > 100: buzz_score += 10
    
    total = trend_score + supply_score + buzz_score
    if total >= 60: return "BUY_STRONG"
    elif total >= 40: return "BUY"
    return "HOLD"

test_df['sentinel_signal'] = test_df.apply(apply_sentinel, axis=1)

# Sentinel Results
sentinel_buys = test_df[test_df['sentinel_signal'].isin(['BUY_STRONG', 'BUY'])]
sen_return = sentinel_buys['next_day_change'].mean() if len(sentinel_buys) > 0 else 0
sen_win_rate = (sentinel_buys['next_day_change'] > 0).mean() * 100 if len(sentinel_buys) > 0 else 0

# ML Results
# Let's say we pick the top X% or prob > threshold. Let's pick prob > 55% as a strong signal
# or just take the top N to match the number of Sentinel buys.
num_sen_buys = len(sentinel_buys)
ml_buys_topN = test_df.nlargest(num_sen_buys, 'ml_prob')

# Let's also test a hard probability cut-off (e.g., > 60%)
ml_buys_prob = test_df[test_df['ml_prob'] >= 60.0]

print("=== 📊 BACKTEST RESULT: SENTINEL vs ML MODEL ===")
print("\n[기존 방식: SentinelV (점수 더하기)]")
print(f"- 추천된 종목 수: {len(sentinel_buys)}개")
print(f"- T+1 평균 예상 수익률: {sen_return:.2f}%")
print(f"- 승률 (상승 확률): {sen_win_rate:.1f}%")

print("\n[새로운 방식: ML 모델 (시간대비율 반영 랜덤포레스트)]")
print(f"(*기존 방식과 똑같이 상위 {len(ml_buys_topN)}개를 뽑았을 때 비교*)")
ml_topN_return = ml_buys_topN['next_day_change'].mean() if len(ml_buys_topN) > 0 else 0
ml_topN_win_rate = (ml_buys_topN['next_day_change'] > 0).mean() * 100 if len(ml_buys_topN) > 0 else 0
print(f"- 추천된 종목 수: {len(ml_buys_topN)}개")
print(f"- T+1 평균 예상 수익률: **{ml_topN_return:.2f}%**")
print(f"- 승률 (상승 확률): **{ml_topN_win_rate:.1f}%**")

print("\n(*ML 모델 기준 상위 60% 이상 확실한 것만 샀을 때*)")
ml_prob_return = ml_buys_prob['next_day_change'].mean() if len(ml_buys_prob) > 0 else 0
ml_prob_win_rate = (ml_buys_prob['next_day_change'] > 0).mean() * 100 if len(ml_buys_prob) > 0 else 0
print(f"- 추천된 종목 수: {len(ml_buys_prob)}개")
print(f"- T+1 평균 예상 수익률: **{ml_prob_return:.2f}%**")
print(f"- 승률 (상승 확률): **{ml_prob_win_rate:.1f}%**")

print("\n[결론]")
if ml_topN_return > sen_return:
    diff = ml_topN_return - sen_return
    print(f"-> ML 방식이 기존 대비 수익률을 {diff:.2f}%p 끌어올렸습니다!")
else:
    print("-> 차이가 미미하거나 비슷합니다.")
