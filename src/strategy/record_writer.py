"""스크래핑 결과 기록 저장.

analyze_discussion_trend가 만든 DataFrame을 대시보드·백테스트용 산출물로 쓴다.
analyzer.py에서 분리됐다(순수 이동). 하위 호환을 위해 analyzer.save_data로도
계속 노출된다.

산출물:
- data/trending_integrated.csv / .xlsx  — 고정(최신) 스냅샷, 대시보드·다운로드용
- data/trending_integrated_{YYYY-MM}.xlsx — 월간 누적(append, 백테스트용)
- data/trending_integrated_{YYYYMMDD_HH}.xlsx — 시간별 스냅샷, 5일/3일 분석기용
- data/latest_stocks.json + status.json — Vercel 대시보드용
"""
import os
import json
import pandas as pd
from datetime import datetime, timedelta


def save_data(df, filename_prefix="trending_stocks", extra_sheets=None, start_time=None):
    """
    [V8.9.9.5] DataFrame을 CSV/Excel/JSON으로 저장합니다.
    - 고정 파일(trending_integrated.xlsx): Vercel 대시보드 및 사이드바 엑셀 다운로드용
    - 날짜별 스냅샷(trending_integrated_YYYYMMDD_HHMMSS.xlsx): 5일/3일 분석기 전용
    """
    if df.empty:
        print("No data to save.")
        return {}

    saved_files = {}
    os.makedirs('data', exist_ok=True)

    # [V8.9.9.11] 기동 시각 동기화 및 스냅샷 시간 단위 통합 (파일 개수 최적화)
    now_kst = start_time if start_time else (datetime.utcnow() + timedelta(hours=9))
    timestamp = now_kst.strftime("%Y%m%d_%H")

    # 1. 고정 CSV 저장 (Force Sync)
    try:
        fixed_csv = "data/trending_integrated.csv"
        df.to_csv(fixed_csv, index=False, encoding='utf-8-sig')
        print(f"\n[Fixed] Data saved to CSV: {os.path.abspath(fixed_csv)}")
        saved_files['csv'] = fixed_csv
    except Exception as e:
        print(f"Error saving to CSV: {e}")

    # 2. 고정 Excel 저장 (사이드바 '★ 최신' 다운로드용)
    try:
        fixed_xlsx = "data/trending_integrated.xlsx"
        with pd.ExcelWriter(fixed_xlsx, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Trending_Stocks', index=False)
            if extra_sheets:
                for sheet_name, sheet_df in extra_sheets.items():
                    if not sheet_df.empty:
                        sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
        print(f"[Fixed] Data saved to Excel: {os.path.abspath(fixed_xlsx)}")
        saved_files['excel'] = fixed_xlsx
    except Exception as e:
        print(f"Error saving to Excel: {e}")

    # 2-1. [V8.9.9.5 User Request] 월간 누적 Excel 저장 (예: trending_integrated_2024-04.xlsx)
    try:
        month_str = now_kst.strftime("%Y-%m")
        monthly_xlsx = f"data/trending_integrated_{month_str}.xlsx"

        # 데이터 수집 시각 컬럼 추가 (누적 데이터 식별용)
        df_monthly = df.copy()
        df_monthly.insert(0, '데이터_수집시각', now_kst.strftime("%Y-%m-%d %H:%M:%S"))

        if os.path.exists(monthly_xlsx):
            try:
                existing_df = pd.read_excel(monthly_xlsx)
                # 새로운 데이터를 하단에 결합 (누적)
                combined_df = pd.concat([existing_df, df_monthly], ignore_index=True)
                # 너무 커지는 것을 방지하거나 중복 처리가 필요할 수 있으나, 일단 누적 (User Request)
                combined_df.to_excel(monthly_xlsx, index=False)
                print(f"[Monthly] Cumulative data appended to: {monthly_xlsx}")
            except Exception as ex:
                print(f"[Monthly] Read/Append failed ({ex}), overwriting as new.")
                df_monthly.to_excel(monthly_xlsx, index=False)
        else:
            df_monthly.to_excel(monthly_xlsx, index=False)
            print(f"[Monthly] New monthly file created: {monthly_xlsx}")

        saved_files['monthly'] = monthly_xlsx
    except Exception as e:
        print(f"Error saving monthly Excel: {e}")

    # 3. [V8.9.9.5 신규] 날짜별 스냅샷 Excel 저장 (5일/3일 분석기 전용)
    # analyzer_5days.py가 trending_integrated_YYYYMMDD_HHMMSS.xlsx 패턴을 탐색함
    try:
        snapshot_xlsx = f"data/trending_integrated_{timestamp}.xlsx"
        with pd.ExcelWriter(snapshot_xlsx, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Trending_Stocks', index=False)
        print(f"[Snapshot] Daily snapshot saved: {os.path.basename(snapshot_xlsx)}")
        saved_files['snapshot'] = snapshot_xlsx

        # [스토리지 절약] 오늘 날짜 파일이 이미 있으면 구파일 제거 (최신 1개만 유지)
        today_prefix = f"data/trending_integrated_{now_kst.strftime('%Y%m%d')}"
        import glob as _glob
        existing_today = sorted(_glob.glob(f"{today_prefix}_*.xlsx"))
        # 새로 저장한 파일 외의 같은 날 파일 제거
        for old_file in existing_today[:-1]:
            try:
                os.remove(old_file)
                print(f"[Cleanup] Removed old snapshot: {os.path.basename(old_file)}")
            except:
                pass
    except Exception as e:
        print(f"Error saving snapshot Excel: {e}")

    # 4. Vercel JSON 저장 (latest_stocks.json + status.json)
    try:
        fixed_json = "data/latest_stocks.json"

        df_for_json = df.copy()

        mapping_pairs = [
            ('recent_posts_count', '게시물'),
            ('prev_close', '전일종가'),
            ('foreign_change', '외인변화'),
            ('foreign_change_rate', '외인변화'),
            ('foreign_change_rate', 'foreign_change'),
            ('foreign_rate', '외인비중'),
            ('prev_foreign_rate', '전일외인'),
            ('consecutive_days', '연속'),
            ('posts_summary', '게시물_요약'),
            ('sentiment', '감정')
        ]

        for eng, kor in mapping_pairs:
            if eng in df_for_json.columns and kor not in df_for_json.columns:
                df_for_json[kor] = df_for_json[eng]
            elif kor in df_for_json.columns and eng not in df_for_json.columns:
                df_for_json[eng] = df_for_json[kor]

        text_fields = ['게시물_요약', 'posts_summary', '감정', 'sentiment', '키워드', 'keywords']
        for field in text_fields:
            if field in df_for_json.columns:
                if '요약' in field or 'summary' in field:
                    df_for_json[field] = df_for_json[field].fillna("분석 대기중")
                elif '감정' in field or 'sentiment' in field:
                    df_for_json[field] = df_for_json[field].fillna("중립 (0)")
                else:
                    df_for_json[field] = df_for_json[field].fillna("")
            else:
                if '요약' in field or 'summary' in field: df_for_json[field] = "분석 대기중"
                elif '감정' in field or 'sentiment' in field: df_for_json[field] = "중립 (0)"
                else: df_for_json[field] = ""

        df_for_json = df_for_json.fillna(0)
        df_for_json = df_for_json.loc[:, ~df_for_json.columns.duplicated()]

        json_data = df_for_json.to_json(orient='records', force_ascii=False)
        with open(fixed_json, 'w', encoding='utf-8') as f:
            f.write(json_data)

        status_str = now_kst.strftime("%Y-%m-%d %H:%M:%S")
        status_json = "data/status.json"
        with open(status_json, 'w', encoding='utf-8') as f:
            json.dump({"last_updated": status_str, "status": "ok", "message": "V8.9.9.11 LIVE-SYNC"}, f, ensure_ascii=False, indent=4)

        print(f"[Vercel] ✅ Fixed data synchronized: latest_stocks.json (V8.9.9.11, Time: {status_str})")
    except Exception as e:
        print(f"[Vercel] 🚨 Error during fixed data synchronization: {e}")

    return saved_files
