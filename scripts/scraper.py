"""
StockBot Pipeline Entry Point
==============================
[V50.1] Explicit Plugin Architecture - Interface Fixed

이 파일은 진입점(Entry Point)입니다. 비즈니스 로직이 없습니다.
모든 로직은 src/pipeline/workers/ 하위 Worker 클래스에 있습니다.

[롤백 방법]
  scripts/scraper_legacy_v49.py 를 scraper.py로 복사하면 즉시 이전 버전으로 복원됩니다.
  git: git checkout v49.2-pre-refactor -- scripts/scraper.py
"""

import os
import sys

# 루트 경로를 Python 경로에 추가 (기존 방식 유지)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# [V8.9.9.5 Hotfix] Windows cp949 인코딩 에러 방지 (Emoji 출력 지원)
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from src.pipeline.context import PipelineContext
from src.pipeline.orchestrator import run_pipeline

if __name__ == "__main__":
    ctx = PipelineContext.from_env()
    run_pipeline(ctx)
