"""매매 경로는 가벼워야 한다 — requirements-trade.txt로 돌 수 있어야 한다.

trading.yml은 2분마다 새 컨테이너에서 pip install을 한다. 셋업이 길수록 루프에
남는 예산이 줄고, 그게 곧 매매 주기의 하한이다. 실측:

    requirements-scraper.txt (pandas·sklearn·pyarrow·pdfplumber·google-genai 포함)
      → pip install 24초, 셋업 총 47초 → 태스커 2분 창에 한 바퀴(=2분 매매)

    requirements-trade.txt (requests·bs4·pydantic·pyyaml·dotenv)
      → 셋업 약 20초 → 두 바퀴(=1분 매매)

그래서 매매 진입점이 무거운 패키지를 import하기 시작하면 1분 매매가 조용히
2분 매매로 되돌아간다. 이 테스트가 그 회귀를 잡는다.

한 번 실제로 새어들었던 경로: trade 진입점 → orchestrator → LLMAnalyzerWorker →
google-genai, 그리고 StorageManager 최상단의 `import pandas`.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# 매매 경로에 들어오면 안 되는 패키지. 전부 requirements-trade.txt에 없다.
FORBIDDEN = ['pandas', 'numpy', 'sklearn', 'joblib', 'pyarrow',
             'openpyxl', 'pdfplumber', 'pypdf']


def _modules_after_importing(module: str) -> set:
    """별도 프로세스에서 import하고 sys.modules 최상위 이름을 돌려준다.

    같은 프로세스에서 재면 다른 테스트가 이미 로드해둔 모듈에 오염된다.
    """
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import %s;"
        "print(','.join(sorted({m.split('.')[0] for m in sys.modules})))" % (REPO, module)
    )
    out = subprocess.run([sys.executable, '-c', code], capture_output=True,
                         text=True, cwd=REPO)
    assert out.returncode == 0, f"import 실패:\n{out.stderr[-2000:]}"
    return set(out.stdout.strip().split(','))


def test_trade_entry_point_stays_light():
    loaded = _modules_after_importing('scripts.trade_loop')
    leaked = sorted(set(FORBIDDEN) & loaded)
    assert not leaked, (
        f"매매 진입점이 무거운 패키지를 끌고 왔다: {leaked}. "
        f"requirements-trade.txt에 없으므로 trading.yml에서 ImportError가 난다. "
        f"해당 import를 쓰는 함수 안으로 옮기거나, 매매 경로에서 그 모듈을 떼어낼 것."
    )


def test_trading_cycle_stays_light():
    """진입점뿐 아니라 매매 사이클 모듈 자체도 가벼워야 한다."""
    loaded = _modules_after_importing('src.pipeline.trading_cycle')
    leaked = sorted(set(FORBIDDEN) & loaded)
    assert not leaked, f"trading_cycle이 무거운 패키지를 끌고 왔다: {leaked}"


def test_requirements_file_exists_and_is_slim():
    path = os.path.join(REPO, 'scripts', 'requirements-trade.txt')
    pkgs = [l.split('==')[0].split('>=')[0].strip().lower()
            for l in open(path, encoding='utf-8')
            if l.strip() and not l.startswith('#')]
    assert 'requests' in pkgs and 'beautifulsoup4' in pkgs
    for bad in ('pandas', 'scikit-learn', 'pyarrow', 'google-genai', 'pdfplumber'):
        assert bad not in pkgs, f"{bad}는 매매 경로에 필요 없다 — 설치 시간만 든다"
