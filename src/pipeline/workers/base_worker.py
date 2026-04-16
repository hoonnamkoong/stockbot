"""
[V50] Worker 베이스 클래스 (BaseWorker)
=======================================================
모든 Worker가 상속하는 공통 기반 클래스입니다.

핵심 기능:
- safe_run(): 실행 실패 시 fallback 함수로 자동 전환
- log(): 클래스명이 포함된 구조화된 로그 출력
"""

from abc import ABC, abstractmethod
from src.pipeline.context import PipelineContext


class BaseWorker(ABC):
    """
    모든 Pipeline Worker의 공통 기반 클래스.
    PipelineContext를 생성자에서 주입받습니다 (의존성 주입).
    """

    def __init__(self, ctx: PipelineContext):
        self.ctx = ctx

    @property
    def name(self) -> str:
        """Worker 이름 (로그 표시용)"""
        return self.__class__.__name__

    def log(self, msg: str) -> None:
        """[WorkerName] 형식의 구조화된 로그를 출력합니다."""
        self.ctx.log(f"[{self.name}] {msg}")

    def log_error(self, msg: str) -> None:
        """에러 로그를 출력합니다."""
        print(f"[{self.name}] ❌ ERROR: {msg}")

    def safe_run(self, primary_func, fallback_func, *args, **kwargs):
        """
        primary_func 실행을 시도하고 실패 시 fallback_func로 전환합니다.
        금융 시스템에서 단일 장애점(SPOF)을 제거하는 핵심 메커니즘입니다.

        Args:
            primary_func: 우선 실행할 함수
            fallback_func: 실패 시 대체 실행할 함수
            *args, **kwargs: 두 함수에 공통으로 전달할 인자

        Returns:
            primary_func 또는 fallback_func의 실행 결과
        """
        try:
            return primary_func(*args, **kwargs)
        except Exception as e:
            self.log_error(f"Primary 실패, Fallback 모드 진입: {e}")
            try:
                return fallback_func(*args, **kwargs)
            except Exception as fe:
                self.log_error(f"Fallback도 실패: {fe}")
                return None
