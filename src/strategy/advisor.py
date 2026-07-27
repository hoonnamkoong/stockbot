import os
import sys
import json
import time
import requests
import urllib.parse
import datetime
from google import genai
from collections import Counter
import re
from bs4 import BeautifulSoup

# [V8.4.6 Gold Master] AI 분석 엔진 및 전략 코디네이터
# 개편 사항: 동적 모델 로더, 환경변수 통합, 데이터 인젝션 안정화

# --- Trade Module Imports ---
from src.trade.auth import get_access_token, load_env
from src.trade.balance import get_balance
from src.data import usage_log

class GeminiAgent:
    """
    [V8.6.0] Fixed Gemini Engine & Singleton Controller
    - 싱글톤 패턴으로 인스턴스 중복 생성 방지
    - 모델 하드코딩 (Batch: Flash-Lite, Report: Pro)
    - 429 발생 시 즉시 중단 (Fail-Fast)
    """
    _instance = None
    exhausted_models = set() # 429(Daily) 발생 모델 기록

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GeminiAgent, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    @staticmethod
    def clean_text(text):
        if not text: return ""
        # ㅋㅋ, ㅎㅎ, ㅠㅠ 등 3번 이상 반복되는 자모음 압축
        text = re.sub(r'([ㄱ-ㅎㅏ-ㅣ])\\1{2,}', r'\\1', text)
        # 불필요한 특수문자 여러개 압축
        text = re.sub(r'([!?.~])\\1{2,}', r'\\1', text)
        # 여러개 공백을 하나로 압축
        text = re.sub(r'\s+', ' ', text)
        return text.strip()[:200]

    def __init__(self):
        if self._initialized: return
        
        # [V8.6.0] 모델 명칭 선설정 (API 키 부재 시에도 속성 참조 가능하도록 보장)
        self.batch_model_name = "gemini-2.5-flash-lite"
        self.report_model_name = "gemini-2.5-flash"
        self.exhausted_models = set() if not hasattr(self, 'exhausted_models') else self.exhausted_models

        self.api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_KEY')
        
        if not self.api_key:
            print("[GeminiAgent] 🚨 에러: API 키가 감지되지 않습니다. 모델은 초기화되지 않았습니다.")
            self.client = None
            self._initialized = True # 반복 에러 방지
            return

        # [2026-06-05] 레거시 google-generativeai(EOL 2025-11-30) → google-genai SDK 이전
        self.client = genai.Client(api_key=self.api_key)

        self._initialized = True
        print(f"[GeminiAgent] ✅ V8.6.0 싱글톤 엔진 가동 (batch={self.batch_model_name}, report={self.report_model_name})")

    # [V8.6.0] 동적 모델 업데이트 로직 폐기 (Fixed Engine 체제)

    # 배치 호출자가 이 값을 채우면 기록 책임이 그쪽으로 넘어간다. 응답 종목 수는
    # 파싱을 끝내야 알 수 있어 호출 직후에는 기록할 수 없기 때문이다.
    # 비어 있으면(리포트 등 단발 호출) _log_usage가 그 자리에서 기록한다.
    _usage_ctx: dict = {}
    _last_usage: dict = {}

    def _log_usage(self, model_name, prompt, response):
        """Gemini 호출 1건을 계측한다.

        SDK가 usage_metadata를 주지 않으면 토큰 칸은 비워 둔다. 0으로 채우면
        '측정값 0'과 '측정 불가'가 구분되지 않는다. 그 경우를 대비해 프롬프트
        길이(req_chars)를 항상 함께 남긴다.
        """
        um = getattr(response, 'usage_metadata', None)
        record = {
            'event': 'batch_call',
            'model': model_name,
            'req_chars': len(prompt) if prompt else 0,
            'prompt_tokens': getattr(um, 'prompt_token_count', '') if um else '',
            'output_tokens': getattr(um, 'candidates_token_count', '') if um else '',
            'total_tokens': getattr(um, 'total_token_count', '') if um else '',
        }
        GeminiAgent._last_usage = record
        if not GeminiAgent._usage_ctx:
            usage_log.append(record)

    def _call_gemini_safe(self, prompt, model_type='batch', generation_config=None):
        """
        [V8.6.0 Fail-Fast] 고정 모델 체제. 429 발생 시 즉시 중단 및 블랙리스트 등록
        model_type: 'batch' (Flash-Lite) or 'report' (Pro)
        """
        target_name = self.batch_model_name if model_type == 'batch' else self.report_model_name

        if not self.client:
            return None
        if target_name in self.exhausted_models:
            print(f"[GeminiAgent] ⛔ {target_name}은 쿼터 소진으로 인해 호출 불가 상태입니다.")
            return None

        try:
            response = self.client.models.generate_content(
                model=target_name, contents=prompt, config=generation_config
            )
            self._log_usage(target_name, prompt, response)
            return response
        except Exception as e:
            err_msg = str(e)
            if ("429" in err_msg or "Quota" in err_msg or "ResourceExhausted" in err_msg):
                print(f"[GeminiAgent] 🚨 Quota Exceeded ({target_name}). 즉시 분석 중단 및 블랙리스트 등록.")
                self.exhausted_models.add(target_name)
            else:
                print(f"[GeminiAgent] 🚨 API 에러 ({target_name}): {err_msg}")
        
        return None

    def analyze_batch_discovery(self, batch_data):
        """
        [V8.5.5] 1차 필터 통과 종목군 일괄 분석 (Batch Discovery)
        - 한 번의 API 호출로 모든 종목의 감정/요약/키워드 추출
        - Quota 절감 및 분석 속도 개선
        """
        if not self.client or not batch_data:
            return {s.get('code', s.get('name')): {"sentiment_score": 0, "summary": "AI 분석 불가", "keywords": []} for s in batch_data}
        
        # [V8.9.9.6] 데이터 경량화 및 정합성 보전 (Body 일부 포함하여 분석 품질 향상)
        # 종목 수가 많을 경우 10개씩 그룹화하여 API 호출
        GROUP_SIZE = 10
        all_results = {}
        
        for i in range(0, len(batch_data), GROUP_SIZE):
            group = batch_data[i:i + GROUP_SIZE]
            cleaned_batch = []
            for stock in group:
                # 추천수가 높은 본문(Body)을 요약에 활용 (글자 수 제한 준수)
                posts_text = "\n".join([f"[{p.get('title')}] {GeminiAgent.clean_text(str(p.get('body', '')))}" for p in stock.get('posts', [])])
                cleaned_batch.append({
                    "code": stock.get('code'),
                    "name": stock.get('name'),
                    "content": posts_text
                })
            
            # 그룹별 프롬프트 생성 및 호출
            prompt = f"""
            당신은 주식 종목 토론방의 대중 심리와 팩트를 분석하는 전문가입니다.
            아래 리스트({len(cleaned_batch)}개 종목)의 데이터를 분석하여 결과를 도출하세요.

            [V8.6.2 분석 규칙 - 강화된 객관성]
            1. 감정적 단어(가즈아, 존버, 떡상 등) 및 선동 문구는 무조건 배제하고 0점 처리.
            2. 다음 핵심 키워드를 반드시 우대하여 분석에 포함: '분석', '추세', '전망', '공시', '뉴스', '따르면', '의하면'.
            3. summary는 내용이 풍부할 경우 2~3문장의 명사형 요약 가능. (예: 외인 매수세 유입에 따른 추세 전환 전망. 공시 기반 신규 수주 확인.)
            4. keywords는 3개 이내 핵심 전문 용어만 추출.

            [분석 대상 데이터]
            {json.dumps(cleaned_batch, ensure_ascii=False)}
            
            각 종목별로 다음 JSON 배열 형식으로만 응답하세요:
            [
                {{
                    "code": "005930",
                    "sentiment": 점수(-10 ~ 10),
                    "summary": "초간결 명사 요약",
                    "keywords": ["키워드1", "키워드2"]
                }}
            ]
            """
            group_before = len(all_results)
            GeminiAgent._usage_ctx = {
                'req_stocks': len(cleaned_batch),
                'req_posts': sum(len(s.get('posts', [])) for s in group),
            }
            try:
                response = self._call_gemini_safe(
                    prompt,
                    model_type='batch',
                    generation_config={"response_mime_type": "application/json"}
                )
                if response and response.text:
                    raw_text = response.text.strip()
                    if raw_text.startswith("```"):
                        raw_text = re.sub(r"^(?:```[a-z]*\n)|(?:```$)", "", raw_text, flags=re.MULTILINE).strip()
                    parsed = json.loads(raw_text)
                    
                    if isinstance(parsed, dict) and 'results' in parsed:
                        parsed = parsed['results']
                        
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict):
                                if 'code' in item:
                                    all_results[item['code']] = item
                                else:
                                    for k, v in item.items():
                                        all_results[k] = v
                    elif isinstance(parsed, dict):
                        all_results.update(parsed)
            except Exception as e:
                print(f"[GeminiAgent] Group Batch 분석 오류: {e}")
            finally:
                # 응답 종목 수를 붙여 기록한다. 요청보다 적으면 flash-lite가 긴
                # JSON 배열에서 종목을 조용히 누락시킨 것이므로, 배치 크기를
                # 올려도 되는지 판단하려면 이 값이 필요하다.
                record = dict(GeminiAgent._last_usage)
                record.update(GeminiAgent._usage_ctx)
                record['resp_stocks'] = len(all_results) - group_before
                usage_log.append(record)
                GeminiAgent._usage_ctx = {}
                GeminiAgent._last_usage = {}

        final_results = {}
        for s in batch_data:
            code = s.get('code')
            final_results[code] = all_results.get(code, {"sentiment": 0, "summary": "분석 오류", "keywords": []})
            
        return final_results

class StrategyAdvisor:
    def __init__(self):
        from .virtual_portfolio import VirtualPortfolioManager
        from .engine import StrategyEngine
        self.vpm = VirtualPortfolioManager()
        self.engine = StrategyEngine()
        self.gemini = GeminiAgent()

    def analyze_batch_discovery(self, batch_data):
        return self.gemini.analyze_batch_discovery(batch_data)

    def select_sell_candidate(self, holdings: list) -> dict:
        """
        [V50.7] 보유 종목 중 매도가 필요한 1종목을 AI가 선정합니다.
        """
        if not holdings:
            return None
            
        def _parse_rate(val):
            if val is None: return 0.0
            try:
                return float(str(val).replace('%', '').replace(',', '').strip())
            except (ValueError, TypeError):
                return 0.0

        # 수익률 낮은 순으로 정렬 후 1종목 선정하여 AI 판단
        sorted_holdings = sorted(holdings, key=lambda x: _parse_rate(x.get('profit_rate', 0)))
        candidate = sorted_holdings[0]

        prompt = f"""
        당신은 전문 트레이더입니다. 아래 보유 종목을 분석하여 현재 시장 상황에서 '매도'가 적절한지 판단하세요.
        
        [보유 종목 데이터]
        {json.dumps(candidate, ensure_ascii=False)}
        
        [선정 기준]
        1. 수익률이 지나치게 높거나 낮은 종목 (익절/손절)
        2. 최근 주가 흐름이 둔화되거나 꺾인 종목
        
        오직 아래 JSON 형식으로만 답변하세요:
        {{
            "code": "종목코드",
            "name": "종목명",
            "reason": "매도 추천 사유 (한 문장)"
        }}
        """
        try:
            response = self.gemini._call_gemini_safe(prompt, model_type='batch', generation_config={"response_mime_type": "application/json"})
            if response and response.text:
                data = json.loads(response.text)
                target = next((h for h in holdings if h['code'] == data.get('code')), None)
                if target:
                    target['sell_reason'] = data.get('reason', '수익/손실 관리 필요')
                    return target
        except:
            pass
        return None

    def _format_investment_block(self, stock: dict, sector_avg: dict | None) -> str:
        """투자 수치 데이터 블록 — Gemini 리포트 뒤에 병합."""
        lines = ["── 투자 데이터 ─────────────────────────"]

        op = stock.get('invest_opinion', '') or ''
        tp = stock.get('target_price', 0) or 0
        div = stock.get('opinion_divergence', 0) or 0
        if op or tp:
            tp_str = f"{tp:,}원 (현재가 대비 {div:+.1f}%)" if tp else "-"
            lines.append(f"종목투자의견: {op or '-'} | 목표가: {tp_str}")

        consensus = stock.get('consensus_summary', '') or ''
        if consensus:
            lines.append(f"컨센서스: {consensus}")

        per = stock.get('per', 0) or 0
        pbr = stock.get('pbr', 0) or 0
        if per or pbr:
            if sector_avg and sector_avg.get('avg_per'):
                avg_per = sector_avg['avg_per']
                avg_pbr = sector_avg.get('avg_pbr', 0)
                per_diff = round((per - avg_per) / avg_per * 100) if avg_per else 0
                per_label = f"업종 평균 {avg_per}x 대비 {per_diff:+d}%"
                pbr_label = f"업종 평균 {avg_pbr}x" if avg_pbr else ""
            else:
                if per < 15:
                    per_label = "저평가 구간"
                elif per < 30:
                    per_label = "적정 구간"
                elif per < 50:
                    per_label = "성장주 수준"
                else:
                    per_label = "고평가 / 성장 기대 반영"
                if pbr < 1:
                    pbr_label = "자산가치 이하"
                elif pbr < 3:
                    pbr_label = "적정"
                else:
                    pbr_label = "성장 프리미엄"

            per_str = f"PER {per}x ({per_label})"
            pbr_str = f"PBR {pbr}x ({pbr_label})" if pbr_label else f"PBR {pbr}x"
            lines.append(f"{per_str} | {pbr_str}")

        w52h = stock.get('w52_hgpr', 0) or 0
        w52l = stock.get('w52_lwpr', 0) or 0
        cur = stock.get('price', stock.get('current_price', 0)) or 0
        if w52h and w52l and cur:
            pos = round((cur - w52l) / (w52h - w52l) * 100) if w52h != w52l else 50
            lines.append(f"52주: 고 {w52h:,}원 / 저 {w52l:,}원 (현재 위치 {pos}%)")

        lines.append("────────────────────────────────────────")
        return "\n".join(lines)

    def generate_deep_dive_report(self, final_candidates, sell_candidate=None):
        """
        딥다이브 리포트 — 5개 섹션 번호 포맷.
        1. 사업 요약  2. 추천 근거  3. 리스크
        4. 투자 데이터 (목표가: KIS 컨센서스 평균)  5. 관련 기사
        """
        if not final_candidates and not sell_candidate:
            return "분석 대상 종목이 없습니다."

        reports = []

        try:
            from src.trade.kis_data_provider import KISDataProvider
            kis = KISDataProvider()
        except Exception:
            kis = None

        try:
            from src.data.sector_cache import SectorCache
            sector_cache = SectorCache()
        except Exception:
            sector_cache = None

        for stock in final_candidates[:2]:
            cur = stock.get('price', stock.get('current_price', 0)) or 0

            # 뉴스 아이템 (제목 + URL)
            news_items = []
            if kis:
                try:
                    news_items = kis.get_news_items(stock['code'], limit=5)
                except Exception:
                    pass

            w52h = stock.get('w52_hgpr', 0) or 0
            w52l = stock.get('w52_lwpr', 0) or 0
            w52_text = ""
            if w52h and w52l and cur:
                pos = round((cur - w52l) / (w52h - w52l) * 100) if w52h != w52l else 50
                w52_text = f"52주 고가 {w52h:,}원 / 저가 {w52l:,}원 (현재 위치 {pos}%)"

            # Gemini 프롬프트용 뉴스 제목
            news_section = ""
            if news_items:
                news_section = "\n[최근 뉴스 제목]\n" + "\n".join(f"- {n['title']}" for n in news_items)

            prompt = f"""당신은 대한민국 주식시장 전문 애널리스트입니다.
아래 정보를 바탕으로 이 종목이 왜 지금 시장의 주목을 받고 있는지 분석하세요.

종목: {stock['name']} ({stock['code']})
현재가: {cur:,}원 | 순위: {stock.get('rank', 'N/A')}위
외인변화: {stock.get('foreign_change', 0):+.2f}%p
{w52_text}
[토론 요약]
{stock.get('posts_summary', '정보 없음')}
{news_section}

다음 JSON 형식으로만 답변하세요. 각 항목은 간결한 명사형 불렛 포인트 배열입니다:
{{
  "rank_and_recommendation": "강력 매수 또는 매수 등 추천 등급",
  "business_bullets": ["주요 사업 핵심 1문장 (핵심 키워드 중심)"],
  "rationale_bullets": ["근거1", "근거2", "근거3 (최대 5개)"],
  "risk_bullets": ["리스크1", "리스크2 (최대 3개)"]
}}"""
            try:
                response = self.gemini._call_gemini_safe(
                    prompt, model_type='report',
                    generation_config={"response_mime_type": "application/json"}
                )
                if not (response and response.text):
                    # [진단] response 비어있음 — 쿼터 소진/API 에러는 _call_gemini_safe에서 None 반환
                    reason = "response=None (쿼터/API 에러)" if response is None else "빈 텍스트"
                    print(f"[DeepDive] ⚠️ {stock['name']} 분석 실패: {reason}")
                    reports.append(f"{stock['name']} 상세 분석 실패")
                    continue

                data = json.loads(response.text)
                recommendation = data.get('rank_and_recommendation', '')
                stock['rank_and_recommendation'] = recommendation  # Sim7 Stage 3.6용

                def to_bullets(v):
                    if isinstance(v, list):
                        return [str(x).strip() for x in v if str(x).strip()]
                    if isinstance(v, str):
                        return [line.strip().lstrip('-•·').strip() for line in v.split('\n') if line.strip()]
                    return []

                biz = to_bullets(data.get('business_bullets', []))
                rationale = to_bullets(data.get('rationale_bullets', []))
                risk = to_bullets(data.get('risk_bullets', []))

                # 섹션 1: 사업 요약
                sec1 = "1. 사업 요약\n" + ("\n".join(f"- {b}" for b in biz) if biz else "- 정보 없음")

                # 섹션 2: 추천 근거
                sec2 = "2. 추천 근거\n" + ("\n".join(f"- {r}" for r in rationale) if rationale else "- 정보 없음")

                # 섹션 3: 리스크
                sec3 = "3. 리스크\n" + ("\n".join(f"- {r}" for r in risk) if risk else "- 정보 없음")

                # 섹션 4: 투자 데이터
                sec4_lines = ["4. 투자 데이터"]
                avg_tp = stock.get('consensus_avg_target', 0) or 0
                buy_cnt = stock.get('consensus_buy_count', 0) or 0
                if avg_tp:
                    sec4_lines.append(f"- 목표가: {avg_tp:,}원 (증권사 {buy_cnt}개사 매수의견 평균)")
                per = stock.get('per', 0) or 0
                pbr = stock.get('pbr', 0) or 0
                if per or pbr:
                    sector_name = stock.get('sector_name', '')
                    sector_avg = sector_cache.get_sector_avg(sector_name) if sector_cache and sector_name else None
                    if sector_avg and sector_avg.get('avg_per'):
                        avg_per = sector_avg['avg_per']
                        avg_pbr = sector_avg.get('avg_pbr', 0)
                        per_diff = round((per - avg_per) / avg_per * 100) if avg_per else 0
                        per_label = f"업종 평균 {avg_per}x 대비 {per_diff:+d}%"
                        pbr_label = f"업종 평균 {avg_pbr}x" if avg_pbr else ""
                    else:
                        per_label = ("고평가 / 성장 기대 반영" if per >= 50 else
                                     "성장주 수준" if per >= 30 else
                                     "적정 구간" if per >= 15 else "저평가 구간")
                        pbr_label = ("성장 프리미엄" if pbr >= 3 else
                                     "적정" if pbr >= 1 else "자산가치 이하")
                    per_str = f"PER {per}x ({per_label})" if per else ""
                    pbr_str = f"PBR {pbr}x ({pbr_label})" if pbr else ""
                    line = " | ".join(filter(None, [per_str, pbr_str]))
                    if line:
                        sec4_lines.append(f"- {line}")
                if w52h and w52l and cur:
                    pos = round((cur - w52l) / (w52h - w52l) * 100) if w52h != w52l else 50
                    sec4_lines.append(f"- 52주: 고 {w52h:,}원 / 저 {w52l:,}원 (현재 위치 {pos}%)")
                sec4 = "\n".join(sec4_lines)

                # 섹션 5: 관련 기사 (최대 3개)
                sec5_lines = ["5. 관련 기사"]
                for item in news_items[:3]:
                    title = item.get('title', '')
                    url = item.get('url', '')
                    if url:
                        sec5_lines.append(f"- [{title}]({url})")
                    elif title:
                        sec5_lines.append(f"- {title}")
                if len(sec5_lines) == 1:
                    sec5_lines.append("- 관련 기사 없음")
                sec5 = "\n".join(sec5_lines)

                formatted = (
                    f"{stock['name']} ({recommendation})\n\n"
                    f"{sec1}\n\n"
                    f"{sec2}\n\n"
                    f"{sec3}\n\n"
                    f"{sec4}\n\n"
                    f"{sec5}"
                )
                reports.append(formatted)
            except Exception as e:
                # [진단] json.loads 실패 또는 response.text 접근 시 raise(ValueError, finish_reason 포함) 캡처
                print(f"[DeepDive] ⚠️ {stock['name']} 분석 예외: {e!r}")
                reports.append(f"{stock['name']} 상세 분석 실패")

        header = f"[Strategic Deep-Dive] 상세 리포트\n"
        header += f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        return header + "\n\n---\n\n".join(reports)
