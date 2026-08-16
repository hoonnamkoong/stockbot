"""
업종별 평균 PER/PBR 기준값 조회.
KOSPI/KOSDAQ 업종 평균 기준 (분기 1회 수동 업데이트).
마지막 업데이트: 2026-06
"""

# 업종명(bstp_kor_isnm) → 평균 PER/PBR 기준값
# 출처: KOSPI/KOSDAQ 업종 통계 (2026년 상반기 기준)
SECTOR_BENCHMARKS: dict[str, dict] = {
    # IT/기술
    "소프트웨어":        {"avg_per": 35.0, "avg_pbr": 4.2},
    "IT소프트웨어":      {"avg_per": 35.0, "avg_pbr": 4.2},
    "반도체":            {"avg_per": 20.0, "avg_pbr": 2.3},
    "IT하드웨어":        {"avg_per": 22.0, "avg_pbr": 2.0},
    "디스플레이":        {"avg_per": 18.0, "avg_pbr": 1.5},
    "통신장비":          {"avg_per": 20.0, "avg_pbr": 2.0},
    "인터넷":            {"avg_per": 32.0, "avg_pbr": 3.8},
    "게임소프트웨어":    {"avg_per": 28.0, "avg_pbr": 3.0},
    # 헬스케어/바이오
    "제약":              {"avg_per": 42.0, "avg_pbr": 3.5},
    "바이오":            {"avg_per": 65.0, "avg_pbr": 5.0},
    "의료기기":          {"avg_per": 38.0, "avg_pbr": 4.0},
    "제약바이오":        {"avg_per": 50.0, "avg_pbr": 4.2},
    # 소비/유통
    "자동차":            {"avg_per": 10.0, "avg_pbr": 0.9},
    "자동차부품":        {"avg_per": 12.0, "avg_pbr": 0.9},
    "유통":              {"avg_per": 18.0, "avg_pbr": 1.5},
    "음식료":            {"avg_per": 20.0, "avg_pbr": 2.0},
    "섬유의류":          {"avg_per": 15.0, "avg_pbr": 1.2},
    "화장품":            {"avg_per": 25.0, "avg_pbr": 3.5},
    "엔터테인먼트":      {"avg_per": 30.0, "avg_pbr": 3.5},
    # 금융
    "금융업":            {"avg_per":  8.0, "avg_pbr": 0.6},
    "은행":              {"avg_per":  7.0, "avg_pbr": 0.5},
    "보험":              {"avg_per":  9.0, "avg_pbr": 0.7},
    "증권":              {"avg_per": 10.0, "avg_pbr": 0.8},
    # 산업재
    "화학":              {"avg_per": 14.0, "avg_pbr": 1.3},
    "건설":              {"avg_per": 10.0, "avg_pbr": 0.8},
    "철강":              {"avg_per": 10.0, "avg_pbr": 0.7},
    "조선":              {"avg_per": 15.0, "avg_pbr": 1.2},
    "기계":              {"avg_per": 14.0, "avg_pbr": 1.1},
    "전기전자":          {"avg_per": 18.0, "avg_pbr": 1.8},
    "에너지":            {"avg_per": 12.0, "avg_pbr": 1.0},
    "전기가스":          {"avg_per": 13.0, "avg_pbr": 0.9},
    "운수창고":          {"avg_per": 12.0, "avg_pbr": 1.0},
    "항공":              {"avg_per": 14.0, "avg_pbr": 1.5},
    # 통신
    "통신서비스":        {"avg_per": 14.0, "avg_pbr": 1.2},
    "통신":              {"avg_per": 14.0, "avg_pbr": 1.2},
    # 부동산
    "부동산":            {"avg_per": 16.0, "avg_pbr": 1.1},
    # KIS 실제 업종명 보강 (2026-08-17 — 미등록으로 탈락하던 것들).
    # 구분자만 다른 건 _norm이 잡으므로 여기엔 **이름 자체가 다른 것만** 넣는다.
    "운송장비부품":      {"avg_per": 12.0, "avg_pbr": 0.9},   # ≈ 자동차부품
    "IT서비스":          {"avg_per": 28.0, "avg_pbr": 3.0},   # ≈ 소프트웨어/SI
    "일반서비스":        {"avg_per": 20.0, "avg_pbr": 1.8},
    "금속":              {"avg_per": 10.0, "avg_pbr": 0.7},   # ≈ 철강
    "기타제조":          {"avg_per": 15.0, "avg_pbr": 1.2},
    "종이목재":          {"avg_per": 11.0, "avg_pbr": 0.7},
    "비금속":            {"avg_per": 12.0, "avg_pbr": 0.8},
    "오락문화":          {"avg_per": 25.0, "avg_pbr": 2.5},
    "농업임업어업":      {"avg_per": 15.0, "avg_pbr": 1.2},
    "의료정밀기기":      {"avg_per": 38.0, "avg_pbr": 4.0},   # ≈ 의료기기
    "운송창고":          {"avg_per": 12.0, "avg_pbr": 1.0},   # KIS는 '운송·창고', 표준어는 '운수창고'
}
# ETF·리츠는 일부러 넣지 않는다 — PER/PBR로 저평가를 논할 대상이 아니다.


class SectorCache:
    """업종별 평균 PER/PBR 조회. 하드코딩 기준값 사용."""

    def ensure_fresh(self):
        """호환성 유지용 no-op. 하드코딩 테이블은 갱신 불필요."""
        pass

    @staticmethod
    def _norm(name: str) -> str:
        """구분자를 지운다. KIS 업종명은 가운뎃점·공백을 쓴다 — `전기·전자`, `IT 서비스`.

        2026-08-17 실측: 이 정규화가 없어 심3 후보의 **39%가 '섹터 미등록'으로 조용히
        탈락**하고 있었다(150종목 중 59). 최다가 `전기·전자` 24종목 — 테이블엔
        `전기전자`로 있는데 부분 매칭이 가운뎃점 하나 때문에 어긋났다.
        """
        return name.replace('·', '').replace('/', '').replace(' ', '').strip()

    def get_sector_avg(self, sector_name: str) -> dict | None:
        """
        업종명(bstp_kor_isnm)으로 평균 PER/PBR 반환.
        부분 매칭 지원: '소프트웨어' → 'IT소프트웨어' 등.
        없으면 None.
        """
        if not sector_name:
            return None
        # 완전 일치
        if sector_name in SECTOR_BENCHMARKS:
            return SECTOR_BENCHMARKS[sector_name]
        # 구분자 제거 후 완전/부분 일치
        target = self._norm(sector_name)
        if not target:
            return None
        for key, val in SECTOR_BENCHMARKS.items():
            if self._norm(key) == target:
                return val
        for key, val in SECTOR_BENCHMARKS.items():
            nk = self._norm(key)
            if target in nk or nk in target:
                return val
        return None
