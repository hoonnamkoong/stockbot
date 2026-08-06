"""
[V50] StockBot 통합 데이터 저장소 (StorageManager)
=======================================================
모든 데이터 I/O의 단일 진입점입니다.
비즈니스 로직(분석, 매매)은 데이터가 어디 저장되는지 알 필요가 없습니다.

현재 저장 대상:
  - GitHub db-data 브랜치 (원격 동기화)
  - data/*.json, data/*.csv, data/reports/*.xlsx (로컬)

향후 DB 마이그레이션 시: 이 파일의 내부 구현만 변경하면 충분합니다.
"""

import os
import json
import glob
import time
import urllib.request
import pandas as pd
from datetime import datetime
from typing import Optional

from src.data.schemas import StockData, SyncState, ReportEntry
from src.strategy.regime_state import read_regime_state


class StorageManager:
    """
    모든 파일 I/O를 담당하는 통합 저장소.
    인스턴스 하나로 전체 파이프라인에서 공유합니다.
    """
    DATA_DIR = "data"
    REPORTS_DIR = "data/reports"
    GITHUB_RAW_BASE = "https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data"

    def __init__(self):
        os.makedirs(self.DATA_DIR, exist_ok=True)
        os.makedirs(self.REPORTS_DIR, exist_ok=True)

    # ================================================================
    # [원격 동기화] GitHub db-data 브랜치 → 로컬 data/
    # ================================================================

    def sync_from_github(self, filenames: list[str]) -> None:
        """
        GitHub db-data 브랜치에서 지정된 파일들을 로컬로 동기화합니다.
        캐시 우회를 위해 타임스탬프 쿼리를 붙입니다.
        기존 load_sync_state()의 파일 동기화 로직을 대체합니다.
        """
        ts = int(time.time())
        for filename in filenames:
            url = f"{self.GITHUB_RAW_BASE}/{filename}?t={ts}"
            local_path = os.path.join(self.DATA_DIR, filename)
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    content = resp.read()
                    mode = 'wb' if filename.endswith('.xlsx') else 'w'
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    if mode == 'wb':
                        with open(local_path, 'wb') as f:
                            f.write(content)
                    else:
                        with open(local_path, 'w', encoding='utf-8') as f:
                            f.write(content.decode('utf-8'))
                print(f"[Storage] [OK] Synced: {filename}")
            except Exception as e:
                print(f"[Storage] [Skip] Sync skipped: {filename} ({e})")

    def get_sync_files_list(self, now_kst: datetime) -> list[str]:
        """동기화할 파일 목록. 심 이름은 매니페스트에서 파생한다.

        예전엔 심 이름을 여기 직접 적어뒀는데, 2026-07-30 심 목록 통합에서 이 자리를
        놓쳤다. 2026-08-04 실측(런 40개 전수)으로 사이클당 26개 시도 중 11개(42%)가
        무의미했다 — 폐기된 심 4개를 계속 부르고, 살아있는 심 9개는 빠져 있었다.
        새 심을 추가할 때 여기를 고칠 일이 없어야 그 사고가 다시 안 난다.
        """
        from src.strategy.registry import get_sim_registry

        base_files = [
            'sync_state.json',
            'consecutive_registry.json',
        ]
        # 분석기(리베로)도 상태 파일을 쓰므로 포함한다.
        for sim in get_sim_registry(include_analyzers=True):
            base_files.append(sim['state_file'])
            base_files.append(sim['csv_file'])
        base_files.append('reservations.json')
        # trade_history_real.csv는 여기 없다 — db-data에 올라가지 않는 비공개 파일이고
        # (scraper.yml 배포 스텝이 명시적으로 제외), 이제는 주문 낸 프로세스가 GitHub
        # API로 직접 쓴다(src/trade/secret_store.py). 부르면 매 사이클 404였다.

        # 월별 리서치 엑셀: 활성 전략 시작월부터 이번 달까지.
        # 2026-01 고정이던 시절엔 전략이 시작하지도 않은 1~3월 파일을 매번 404로
        # 받아왔다.
        curr = self._monthly_report_start(now_kst)
        while curr <= now_kst:
            base_files.append(f"reports/monthly_research_{curr.strftime('%Y-%m')}.xlsx")
            if curr.month == 12:
                curr = datetime(curr.year + 1, 1, 1)
            else:
                curr = datetime(curr.year, curr.month + 1, 1)
        return base_files

    @staticmethod
    def _monthly_report_start(now_kst: datetime) -> datetime:
        """활성 전략의 since(월 초). 읽지 못하면 이번 달만 본다.

        모르는 값을 2026-01 같은 과거로 폴백하면 존재하지 않는 파일을 다시 훑는다.
        """
        try:
            from src.strategy.registry import get_active_strategy_since
            since = get_active_strategy_since()
            if since:
                return datetime(since.year, since.month, 1)
        except Exception:
            pass
        return datetime(now_kst.year, now_kst.month, 1)

    # ================================================================
    # [상태 파일] sync_state.json
    # ================================================================

    def load_sync_state(self, today_str: str) -> tuple[SyncState, dict]:
        """
        sync_state.json을 로드합니다.
        날짜가 바뀌면 일일 제한 목록을 초기화하고 어제 데이터를 반환합니다.
        """
        path = os.path.join(self.DATA_DIR, 'sync_state.json')
        yesterday_data = {}

        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)

                last_date = raw.get('last_update_date', '')
                if last_date != today_str:
                    # 날짜 교체: 어제 연속일수 기록 보존 후 초기화
                    for code, info in raw.get('stocks', {}).items():
                        yesterday_data[code] = {
                            'consecutive_days': info.get('consecutive_days', 1),
                            'last_nid': info.get('last_nid')
                        }
                    return SyncState(last_update_date=today_str), yesterday_data

                # [마이그레이션 대응] 신규 필드가 추가된 SyncState로 안전하게 로드
                state = SyncState(**raw)
                return state, yesterday_data
            except Exception as e:
                print(f"[Storage] sync_state 로드 실패, 초기화: {e}")

        return SyncState(last_update_date=today_str), yesterday_data

    def save_sync_state(self, state: SyncState) -> None:
        """sync_state.json을 저장합니다."""
        path = os.path.join(self.DATA_DIR, 'sync_state.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state.model_dump(), f, ensure_ascii=False, indent=2)

    # ================================================================
    # [매매 이력] CSV 추가
    # ================================================================

    # ================================================================
    # [월별 리서치 엑셀] 누적 업데이트
    # ================================================================

    def _load_market_regime(self) -> tuple:
        """Sim0 리베로 state에서 시장 국면, bull_score, 상세 메트릭스를 읽는다."""
        d = read_regime_state(self.DATA_DIR)
        if d is None:
            return "-", None, None, None, None, None, None
        metrics = d.get("metrics", {})
        return (
            d.get("current_regime", "-"),
            d.get("bull_score"),
            d.get("regime_confidence"),
            metrics.get("breadth_score"),
            metrics.get("momentum_score"),
            metrics.get("trend_strength"),
            metrics.get("volatility_score"),
        )

    def update_monthly_excel(self, picks: list, now_kst: datetime) -> Optional[str]:
        """
        월별 통합 리서치 엑셀에 신규 row를 추가합니다.
        picks는 StockData 또는 dict 모두 허용합니다 (호환성).
        """
        if not picks:
            return None

        month_str = now_kst.strftime('%Y-%m')
        filepath = os.path.join(self.REPORTS_DIR, f"monthly_research_{month_str}.xlsx")

        # Sim0 리베로의 시장 국면 판단을 함께 기록
        regime, bull_score, regime_conf, breadth, momentum, trend_str, volatility = self._load_market_regime()

        new_rows = []
        for p in picks:
            d = p.to_dict() if isinstance(p, StockData) else p
            sparkline = d.get('sparkline_price', []) or []
            new_rows.append({
                'DateTime': now_kst.strftime('%Y-%m-%d %H:%M'),
                'Rank': d.get('rank', '-'),
                'Market': d.get('market', 'Unknown'),
                'Stock': d.get('name', 'Unknown'),
                'Code': d.get('code', 'Unknown'),
                'Signal': d.get('signal', 'WATCH'),
                # ── Sim0 장 현황 ────────────────────────────────
                'Market Regime': regime,
                'Bull Score': bull_score,
                'Regime Confidence': regime_conf,
                'Breadth': breadth,
                'Momentum': momentum,
                'Trend Strength': trend_str,
                'Volatility': volatility,
                # ── 기존 시뮬레이터 입력 필드 ───────────────────
                'Current Price': d.get('price', d.get('current_price', 0)),
                'Change Rate': d.get('change_rate', ''),
                'Volume': d.get('volume', 0),
                'Amount': d.get('amount', 0),
                'Tick Power': d.get('tick_power', 0),
                'Foreign Rate': d.get('foreign_rate', 0),
                'Foreign Change': d.get('foreign_change', 0),
                'Posts Count': d.get('recent_posts_count', 0),
                'Consecutive Days': d.get('consecutive_days', 1),
                'Bid Ask Ratio': d.get('bid_ask_ratio', 1.0),
                'Sparkline': ','.join(str(x) for x in sparkline),
                'Sentiment': d.get('sentiment', 'Neutral'),
                # ── KIS API 보강 필드 ─────────────────────────
                'Frgn Est NetBuy': d.get('frgn_fake_ntby_qty', 0),
                'Inst Est NetBuy': d.get('orgn_fake_ntby_qty', 0),
                'ROE': d.get('roe', 0),
                'Debt Ratio': d.get('debt_ratio', 0),
                'Invest Opinion': d.get('invest_opinion', ''),
                'Target Price': d.get('target_price', 0),
                'Opinion Divergence': d.get('opinion_divergence', 0),
                'Consensus Buy': d.get('consensus_buy_count', 0),
                'Consensus Avg Target': d.get('consensus_avg_target', 0),
                'Consensus Summary': d.get('consensus_summary', ''),
                # ── 밸류에이션/52주 (inquire-price 확장) ────────
                'PER': d.get('per', 0),
                'PBR': d.get('pbr', 0),
                'EPS': d.get('eps', 0),
                'BPS': d.get('bps', 0),
                'W52 High': d.get('w52_hgpr', 0),
                'W52 Low': d.get('w52_lwpr', 0),
                'Mkt Cap(억)': d.get('mkt_cap', 0),
                # ── 리포트 텍스트 ──────────────────────────────
                'Key Drivers': d.get('deep_dive_text', str(d.get('posts_summary', '')))[:2000],
            })

        new_df = pd.DataFrame(new_rows)

        try:
            if os.path.exists(filepath):
                existing_df = pd.read_excel(filepath)
                final_df = pd.concat([existing_df, new_df], ignore_index=True)
            else:
                final_df = new_df

            final_df.to_excel(filepath, index=False)
            print(f"[Storage] 월별 리서치 엑셀 업데이트: {filepath}")

            # reports.json 자동 재생성
            self.rebuild_reports_index(now_kst)
            return filepath

        except Exception as e:
            print(f"[Storage] 엑셀 업데이트 실패: {e}")
            return None

    def rebuild_reports_index(self, now_kst: datetime) -> None:
        """
        data/reports/monthly_research_*.xlsx 를 glob으로 전수 스캔하여
        reports.json을 완전히 재생성합니다.
        단일 파일이 이 인덱스를 관리하므로 불일치가 구조적으로 불가능합니다.
        """
        reports = []
        pattern = os.path.join(self.REPORTS_DIR, 'monthly_research_*.xlsx')

        for fpath in sorted(glob.glob(pattern), reverse=True):
            fname = os.path.basename(fpath)
            try:
                month_part = fname.replace('monthly_research_', '').replace('.xlsx', '')
                y, m = month_part.split('-')
                reports.append(ReportEntry(
                    type="research",
                    title=f"{y}년 {int(m)}월 분석 리포트",
                    date=now_kst.strftime('%Y-%m-%d'),
                    filename=fname,
                    month=month_part,
                    timestamp=now_kst.timestamp()
                ).model_dump())
            except Exception as e:
                print(f"[Storage] reports.json 항목 생성 실패: {fname} ({e})")

        reports_path = os.path.join(self.DATA_DIR, 'reports.json')
        with open(reports_path, 'w', encoding='utf-8') as rf:
            json.dump(reports, rf, ensure_ascii=False, indent=2)
        print(f"[Storage] reports.json 재생성 완료 ({len(reports)}개 항목)")

    # ================================================================
    # [연속 카운트 레지스트리] 독립 누적 관리
    # ================================================================

    def load_consecutive_registry(self) -> dict:
        """연속 카운트 등록부를 로드합니다."""
        path = os.path.join(self.DATA_DIR, 'consecutive_registry.json')
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {"last_reset_date": "", "counts": {}}

    def save_consecutive_registry(self, registry: dict) -> None:
        """연속 카운트 등록부를 저장합니다."""
        path = os.path.join(self.DATA_DIR, 'consecutive_registry.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)

    def update_consecutive_counts(self, passed_codes: list[str], now_kst: datetime) -> dict:
        """
        [수정됨] 개별 종목별 마지막 포착일(last_seen_date)을 기록하여,
        당일 중 나중에 포착되더라도 연속일수가 0으로 증발하지 않도록 보호합니다.
        """
        registry = self.load_consecutive_registry()
        today_str = now_kst.strftime('%Y%m%d')
        counts = registry.get("counts", {})
        last_seen = registry.get("last_seen_date", {})
        
        updated = False
        
        for code in passed_codes:
            seen_date = last_seen.get(code, "")
            
            if seen_date != today_str:
                if seen_date:
                    try:
                        from datetime import datetime
                        last_d = datetime.strptime(seen_date, "%Y%m%d")
                        now_d = datetime.strptime(today_str, "%Y%m%d")
                        diff = (now_d - last_d).days
                        
                        # 주말 및 공휴일 감안 (최대 4일 이내 재포착 시 연속으로 인정)
                        if diff <= 4:
                            counts[code] = counts.get(code, 0) + 1
                        else:
                            counts[code] = 1
                    except Exception:
                        counts[code] = 1
                else:
                    counts[code] = 1
                
                last_seen[code] = today_str
                updated = True

        # 최근 5일 이상 장기간 미포착된 데이터 삭제 처리 (가비지 컬렉터)
        keys_to_del = []
        for code, ldate in last_seen.items():
            if ldate != today_str:
                try:
                    from datetime import datetime
                    diff = (datetime.strptime(today_str, "%Y%m%d") - datetime.strptime(ldate, "%Y%m%d")).days
                    if diff > 5: keys_to_del.append(code)
                except Exception:
                    keys_to_del.append(code)
                
        for k in keys_to_del:
            counts.pop(k, None)
            last_seen.pop(k, None)
            updated = True
            
        if updated:
            registry["counts"] = counts
            registry["last_seen_date"] = last_seen
            self.save_consecutive_registry(registry)
            
        return counts

    # ================================================================
    # [최신 종목 데이터] latest_stocks.json
    # ================================================================

    def save_latest_stocks(self, stocks: list, now_kst: datetime) -> None:
        """최신 분석 결과를 latest_stocks.json과 status.json에 저장합니다."""
        stocks_path = os.path.join(self.DATA_DIR, 'latest_stocks.json')
        status_path = os.path.join(self.DATA_DIR, 'status.json')

        data = [s.to_dict() if isinstance(s, StockData) else s for s in stocks]

        with open(stocks_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        with open(status_path, 'w', encoding='utf-8') as f:
            json.dump({
                "last_updated": now_kst.strftime('%Y-%m-%d %H:%M:%S'),
                "stock_count": len(data)
            }, f, ensure_ascii=False, indent=2)

        print(f"[Storage] latest_stocks.json 저장 완료 ({len(data)}개)")
