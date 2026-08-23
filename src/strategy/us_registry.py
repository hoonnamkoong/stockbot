"""us_strategy_manifest.yaml 전용 레지스트리. src/strategy/registry.py(국내)와
완전히 분리돼 있다 — 서로 import하지 않는다."""
import importlib
import os

import yaml

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), 'us_strategy_manifest.yaml')


def _load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f)


def _load_class(module_path: str, class_name: str):
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_us_sim_registry() -> list[dict]:
    out = []
    for s in _load_manifest().get('simulators', []):
        if not s.get('active', True):
            continue
        out.append({
            'id': s['id'], 'ui_key': s['ui_key'], 'label': s['label'],
            'short_desc': s['short_desc'], 'chart_group': s['chart_group'],
            'color': s['color'], 'state_file': s['state_file'], 'csv_file': s['csv_file'],
            'tradeable': bool(s.get('tradeable', False)), 'currency': s.get('currency', 'USD'),
            'display_order': s.get('display_order', 9999),
        })
    return sorted(out, key=lambda x: x['display_order'])


def get_active_us_simulators() -> list:
    sims = []
    for s in _load_manifest().get('simulators', []):
        if not s.get('active', True):
            continue
        cls = _load_class(s['module'], s['class'])
        sims.append(cls())
    return sims


def get_us_simulator_by_id(sim_id: str):
    for s in _load_manifest().get('simulators', []):
        if s['id'] == sim_id and s.get('active', True):
            cls = _load_class(s['module'], s['class'])
            return cls()
    return None
