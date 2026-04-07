import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys
import json
import concurrent.futures
import re

# [V8.4.7 Gold Master] 아키텍처 안정화 버전 (휴장일 판별 및 리포트 중단 방지)
# [V8.9.9.2] 데이터 정상화: 외인 변화량 계산 및 연속 일수 상태 영구 저장
SCRAPER_VERSION = "8.9.9.2 Data Recovery"

# 경로 설정
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src', 'strategy')))
from src.strategy import analyzer
from src.strategy.advisor import StrategyAdvisor

# --- [V8.4.4] Helper Functions ---
def get_current_kst_time():
    return datetime.utcnow() + timedelta(hours=9)

def get_threshold_by_time(hour):
    """
    [V8.5.0] 사용자 지정 일 누적 Buzz 문턱값 최종 적용
    """
    if 0 <= hour < 9: return 20       # 08:59까지
    elif 9 <= hour < 11: return 40    # 10:00대까지
    elif 11 <= hour < 14: return 80   # 13:00대까지
    elif 14 <= hour < 16: return 120  # 15:00대까지
    return 130 # 16:00 이후 최종 누적 기준

def is_trading_day(dt):
    """
    [V8.4.7] 2026년 한국거래소(KRX) 휴장일 판별 함수
    """
    if dt.weekday() >= 5: return False
    holidays_2026 = [
        "01-01", "02-16", "02-17", "02-18", "03-01", "03-02",
        "05-05", "05-22", "06-06", "08-15", "09-24", "09-25", "09-26",
        "10-03", "10-09", "12-25", "12-31"
    ]
    if dt.strftime('%m-%d') in holidays_2026: return False
    return True

def load_env_manual():
    for filepath in [".env", ".env.local"]:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip() and not line.startswith('#'):
                        try:
                            key, val = line.strip().split('=', 1)
                            os.environ[key.strip()] = val.strip().strip('"').strip("'")
                        except: continue
    gemini_key = os.environ.get('GEMINI_KEY')
    google_key = os.environ.get('GOOGLE_API_KEY')
    if gemini_key and not google_key: os.environ['GOOGLE_API_KEY'] = gemini_key
    elif google_key and not gemini_key: os.environ['GEMINI_KEY'] = google_key

def load_sync_state():
    """
    [V8.9.9.4] sync_state.json에서 어제의 종목 이력 및 연속 등록 일수를 로드합니다.
    """
    state_path = 'data/sync_state.json'
    today_str = get_current_kst_time().strftime('%Y%m%d')
    yesterday_data = {} # {code: {'consecutive_days': n, 'last_nid': '...'}}
    
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
                stocks = state.get('stocks', {})
                
                # 날짜가 바뀌었다면 어제의 데이터를 yesterday_data로 넘김
                if state.get('last_update_date') != today_str:
                    for code, info in stocks.items():
                        yesterday_data[code] = {
                            'consecutive_days': info.get('consecutive_days', 1),
                            'last_nid': info.get('last_nid')
                        }
                    return {'last_update_date': today_str, 'stocks': {}}, yesterday_data
                
                # 오늘 이미 실행된 적이 있다면 어제 데이터는 현재 상태에서 역산하거나 빈 값으로 처리
                # (실시간 업데이트 중이므로 yesterday_data는 새벽 첫 실행 시에만 유효)
                return state, yesterday_data 
        except: pass
    return {'last_update_date': today_str, 'stocks': {}}, yesterday_data

def save_sync_state(state):
    os.makedirs('data', exist_ok=True)
    with open('data/sync_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def extract_nid(link):
    match = re.search(r'nid=(\d+)', link)
    return match.group(1) if match else None

def get_discussion_stats(code, threshold_time, prev_state):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    stock_state = prev_state.get(code, {'cumulative_count': 0, 'last_nid': None})
    new_posts = []
    today_prefix = get_current_kst_time().strftime('%Y.%m.%d')
    found_prev_marker = False
    found_by_nid = False
    for page in range(1, 51):
        if found_prev_marker: break
        url = f"https://finance.naver.com/item/board.naver?code={code}&page={page}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200: break
            soup = BeautifulSoup(res.content, 'html.parser')
            rows = soup.select('table.type2 tr')
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5: continue
                date_text = cols[0].get_text(strip=True)
                if not date_text: continue
                try:
                    full_date = f"{today_prefix} {date_text}" if ":" in date_text and "." not in date_text else date_text
                    post_date = datetime.strptime(full_date, "%Y.%m.%d %H:%M")
                except: continue
                title_tag = row.select_one('td.title a')
                if not title_tag: continue
                current_nid = extract_nid(title_tag['href'])
                if current_nid == stock_state['last_nid']:
                    found_prev_marker = found_by_nid = True
                    break
                if post_date < threshold_time:
                    found_prev_marker = True
                    break
                new_posts.append({
                    'nid': current_nid,
                    'title': title_tag.get_text(strip=True),
                    'likes': cols[4].get_text(strip=True) if len(cols) > 4 else '0',
                    'link': title_tag['href'],
                    'time': post_date.strftime('%Y-%m-%d %H:%M')
                })
        except: break
    new_count = len(new_posts)
    total_cumulative = new_count if stock_state['last_nid'] and not found_by_nid else stock_state['cumulative_count'] + new_count
    latest_nid = new_posts[0]['nid'] if new_posts else stock_state['last_nid']
    sorted_posts = sorted(new_posts, key=lambda x: int(x['likes']) if str(x['likes']).isdigit() else 0, reverse=True)
    return {
        'recent_posts_count': total_cumulative, 
        'representative_posts': sorted_posts[:5],
        'updated_state': {'cumulative_count': total_cumulative, 'last_nid': latest_nid}
    }

def get_stock_details(code):
    """
    [V8.9.9.2] 네이버 금융 '투자자별 매매동향' 테이블 정밀 분석
    - 외국인 보유율, 전일 외국인 보유율, 외인 순매수량, 외인 비중 변화량(%p), 전일 종가 수집
    """
    details = {
        'prev_close': 0,
        'foreign_rate': 0.0,
        'prev_foreign_rate': 0.0,
        'foreign_change': 0.0,     # 비중 변화량 (%p)
        'foreign_change_rate': 0.0, # (UI 호환용) 비중 변화량
        'foreign_net_buy': 0       # 외인 순매수량 (주식 수)
    }
    url_frgn = f"https://finance.naver.com/item/frgn.naver?code={code}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(url_frgn, headers=headers, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        rows = soup.select('table.type2 tr')
        data_rows = []
        for r in rows:
            tds = r.select('td')
            # 9개 컬럼이며, 첫 번째 컬럼이 날짜(YYYY.MM.DD) 형식인 경우만 데이터 행으로 인정
            if len(tds) == 9:
                date_text = tds[0].get_text(strip=True)
                if re.match(r'\d{4}\.\d{2}\.\d{2}', date_text):
                    data_rows.append(tds)
        
        if len(data_rows) >= 2:
            # 1. 외인 보유율 및 순매수량 (첫 번째 행 = 오늘)
            try:
                today_fr_text = data_rows[0][8].get_text(strip=True).replace('%', '')
                details['foreign_rate'] = float(today_fr_text) if today_fr_text else 0.0
                
                # 7번째 컬럼 (index 6): 외국인 순매수량
                net_buy_text = data_rows[0][6].get_text(strip=True).replace(',', '')
                details['foreign_net_buy'] = int(net_buy_text) if net_buy_text.lstrip('-').isdigit() else 0
            except: pass

            # 2. 전일 데이터 (두 번째 행 = 어제)
            try:
                prev_fr_text = data_rows[1][8].get_text(strip=True).replace('%', '')
                details['prev_foreign_rate'] = float(prev_fr_text) if prev_fr_text else 0.0
                
                # 전일 종가 (index 1)
                prev_close_text = data_rows[1][1].get_text(strip=True).replace(',', '')
                if prev_close_text.isdigit(): details['prev_close'] = int(prev_close_text)
            except: pass

            # 3. 비중 변화량 연산 (%p)
            details['foreign_change'] = round(details['foreign_rate'] - details['prev_foreign_rate'], 3)
            details['foreign_change_rate'] = details['foreign_change'] # UI에서 foreign_change_rate를 기대함
            
            print(f"   [Scrape] {code}: 비중 {details['foreign_rate']}%, 변화 {details['foreign_change']}%p, 순매수 {details['foreign_net_buy']}, 전일종가 {details['prev_close']}")
    except Exception as e:
        print(f"   [Warning] {code} 상세 정보 수집 실패: {e}")
    return details

def calculate_consecutive_days(current_codes):
    """
    [V8.9.9.4] 기존 설계 데이터 반영: data 폴더의 과거 엑셀 파일을 역순으로 조회하여 연속 일수 산출
    """
    consecutive_counts = {code: 1 for code in current_codes}
    active_codes = set(current_codes)
    data_dir = 'data'
    if not os.path.exists(data_dir): return consecutive_counts
    pattern = re.compile(r'trending_integrated_(\d{8})_(\d{6})\.(xlsx|csv)$')
    date_files = {}
    for filename in os.listdir(data_dir):
        match = pattern.match(filename)
        if match:
            d_str, t_str = match.group(1), match.group(2)
            try:
                date_fmt = datetime.strptime(d_str, '%Y%m%d').strftime('%Y-%m-%d')
                if date_fmt not in date_files: date_files[date_fmt] = []
                date_files[date_fmt].append((t_str, os.path.join(data_dir, filename)))
            except: continue
    sorted_dates = sorted(date_files.keys(), reverse=True)
    if not sorted_dates: return consecutive_counts
    latest_date = sorted_dates[0]
    for d_str in sorted_dates:
        if d_str == latest_date: continue
        if not active_codes: break
        files = sorted(date_files[d_str], key=lambda x: x[0], reverse=True)
        filepath = files[0][1]
        try:
            if filepath.endswith('.csv'):
                try: df = pd.read_csv(filepath, dtype=str)
                except: df = pd.read_csv(filepath, dtype=str, encoding='cp949')
            else: df = pd.read_excel(filepath, dtype=str)
            target_cols = ['종목코드', 'Code', 'code', 'Symbol', 'symbol']
            found_col = next((col for col in target_cols if col in df.columns), df.columns[0])
            day_codes = set(df[found_col].astype(str).str.replace('A', '').str.zfill(6).tolist())
            next_active = set()
            for code in active_codes:
                if code in day_codes:
                    consecutive_counts[code] += 1
                    next_active.add(code)
            active_codes = next_active
        except: continue
    return consecutive_counts

def process_single_stock(stock, yesterday_data, threshold, threshold_time, prev_sync_state):
    """
    [V8.9.9.2] 단일 종목 처리: 수급 데이터 수집 + 토론방 분석 + 연속 일수 계산
    """
    try:
        code = stock['code']
        # 1. 네이버 금융 수급 상세 데이터 수집
        details = get_stock_details(code)
        stock.update(details)
        
        # 2. 토론방 Buzz 분석
        stats = get_discussion_stats(code, threshold_time, prev_sync_state)
        count = stats.get('recent_posts_count', 0)
        
        # 3. 임계값(Buzz) 통과 여부 확인
        if count >= threshold:
            print(f"   [Buzz] {stock['name']}: {count} posts (PASS)")
            stock['recent_posts_count'] = count
            stock['representative_posts'] = stats.get('representative_posts', [])
            
            # 4. 연속 일수(Consecutive Days) 업데이트 로직
            # 어제 이력이 있으면 +1, 없으면 1
            prev_info = yesterday_data.get(code, {})
            consecutive = prev_info.get('consecutive_days', 0) + 1
            stock['consecutive_days'] = consecutive
            stock['is_consecutive'] = consecutive > 1
            
            updated_info = stats.get('updated_state', {})
            updated_info.update({
                'name': stock['name'], 
                'market': stock.get('market', 'KOSPI'),
                'consecutive_days': consecutive
            })
            return stock, {code: updated_info}
            
        # 임계값 미달 시 연속 일수 리셋 (0 또는 제거)
        return None, {code: stats.get('updated_state', {})}
    except Exception as e:
        print(f"[Error] {stock.get('name', 'Unknown')} 처리 중 오류: {e}")
        return None, None

if __name__ == "__main__":
    start_time = time.perf_counter()
    load_env_manual()
    now_kst = get_current_kst_time()
    force_run = os.environ.get('FORCE_RUN', 'false').lower() == 'true'
    is_open_day = is_trading_day(now_kst)
    threshold = 1 if force_run else get_threshold_by_time(now_kst.hour)
    threshold_time = now_kst.replace(hour=8, minute=0, second=0, microsecond=0)
    print(f"[System] {SCRAPER_VERSION} 가동 (개장일: {is_open_day}, 임계값: {threshold})")
    candidates = []
    for m in ['KOSPI', 'KOSDAQ']:
        candidates.extend(analyzer.get_top_trending_stocks(m))
        candidates.extend(analyzer.get_top_rising_stocks(m))
    unique_candidates = list({s['code']: s for s in candidates}.values())
    print(f"[System] 유니크 후보 {len(unique_candidates)}개 수집 완료")
    prev_sync_state, yesterday_data = load_sync_state()
    current_stocks_state = prev_sync_state.get('stocks', {})
    results = []
    updated_full_state = current_stocks_state.copy()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_single_stock, s, yesterday_data, threshold, threshold_time, current_stocks_state) for s in unique_candidates]
        for f in concurrent.futures.as_completed(futures):
            res_stock, res_state = f.result()
            if res_state: updated_full_state.update(res_state)
            if res_stock: results.append(res_stock)
    
    prev_sync_state['stocks'] = updated_full_state
    save_sync_state(prev_sync_state)
    print(f"[System] Global Recovery 가동...")
    recovered_count = 0
    for code, s_state in updated_full_state.items():
        if s_state.get('cumulative_count', 0) >= threshold:
            if not any(r['code'] == code for r in results):
                results.append({
                    'code': code, 'name': s_state.get('name', 'Unknown'),
                    'market': s_state.get('market', 'KOSPI'),
                    'recent_posts_count': s_state['cumulative_count'],
                    'representative_posts': [], 'is_consecutive': False
                })
                recovered_count += 1
    if recovered_count > 0: print(f"[System] Global Recovery 완료: {recovered_count}개 종목 복구됨")
    if results:
        # [V8.9.9.2] 연속 일수는 process_single_stock에서 이미 계산됨
        print(f"[System] 연속 일수(Consecutive Days) 동기화 완료")
    print(f"[System] 최종 분석 대상: {len(results)}개 종목")
    if results:
        print(f"[System] Gemini Batch AI 분석 시작...")
        advisor = StrategyAdvisor()
        batch_results, chunk_size = {}, 10
        for i in range(0, len(results), chunk_size):
            if advisor.gemini.batch_model_name in advisor.gemini.exhausted_models: break
            chunk = results[i:i + chunk_size]
            batch_input = [{"code": r['code'], "name": r['name'], "posts": r.get('representative_posts', [])} for r in chunk]
            chunk_res = advisor.analyze_batch_discovery(batch_input)
            if chunk_res: batch_results.update(chunk_res)
            if i + chunk_size < len(results): time.sleep(3)
        for r in results:
            insight = batch_results.get(r['code'], {"sentiment_score": 0, "summary": "분석 대기중", "keywords": []})
            r.update({'posts_summary': insight.get('summary', '분석 대기중'), 'keywords': insight.get('keywords', []), 'sentiment_score': insight.get('sentiment_score', 0)})
    if results:
        final_df, _ = analyzer.analyze_discussion_trend(results)
        analyzer.save_data(final_df, "trending_integrated")
        print(f"[System] 리서치 데이터 저장 완료")
    advisor_report, elite_candidates = "", sorted(results, key=lambda x: x.get('recent_posts_count', 0), reverse=True)[:15]
    if elite_candidates:
        advisor_report = advisor.generate_deep_dive_report(elite_candidates[:5])
    else: advisor_report = "⚠️ 금일 분석 기준 충족 종목 없음"
    from src.notification.notification_service import NotificationService
    ns = NotificationService()
    if ns.is_available:
        try:
            kospi_items = final_df[final_df['시장구분'] == 'KOSPI'].to_dict('records')
            kosdaq_items = final_df[final_df['시장구분'] == 'KOSDAQ'].to_dict('records')
        except:
            kospi_items = [r for r in results if r.get('market') == 'KOSPI']
            kosdaq_items = [r for r in results if r.get('market') == 'KOSDAQ']
        ns.send_hourly_report(kospi_records=kospi_items, kosdaq_records=kosdaq_items, advisor_report_text=advisor_report if results else "ℹ️ 기준 충족 종목 없음")
    from src.strategy.simulators.original_simulator import OriginalSimulator
    from src.strategy.simulators.aggressive_simulator import AggressiveSimulator
    from src.strategy.simulators.conviction_simulator import ConvictionSimulator
    for r in results:
        if not r.get('reason'): r['reason'] = r.get('posts_summary', '시장 관심도 증가 기반 매수')
    results_codes = [r['code'] for r in results]
    sim1, sim2, sim3 = OriginalSimulator(), AggressiveSimulator(), ConvictionSimulator()
    sim1.check_liquidation(results_codes)
    if force_run or is_open_day: sim1.execute_strategy(results)
    sim2.check_maintenance()
    if force_run or is_open_day: sim2.execute_strategy(results)
    sim3.check_liquidation(results_codes)
    if force_run or is_open_day: sim3.execute_strategy(results)
    print(f"[System] 프로세스 종료 ({time.perf_counter() - start_time:.2f}s)")
