# 서브모듈을 여기서 즉시 import하지 않는다.
#
# 예전에는 analyzer·advisor·engine을 미리 불러뒀는데, 그 셋이 pandas와
# google-genai를 끌고 오는 바람에 이 패키지의 무엇 하나라도 건드리면 LLM
# 스택 전체가 딸려왔다. 심 하나만 돌리려는 EOD 배치나, 표준 라이브러리만
# 쓰던 daily_brief 같은 가벼운 소비자가 전부 그 비용을 물었다.
#
# 소비자는 모두 `from src.strategy.advisor import X` 또는
# `from src.strategy import analyzer` 꼴로 서브모듈을 명시해서 쓰고 있어
# (2026-07-29 전수 확인) 이 즉시 import에 기대는 곳은 없다.
