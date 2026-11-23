"""다른 코드와의 연결.

Collatio(거르기)는 같은 저장소의 패키지라 그냥 불러 쓴다. 2026-11-23에 kfin-eval을 Collatio 저장소로 합쳤다.
ShockLens(리스크 문항의 정답 계산)는 별도 저장소다. 위치를 환경변수로 지정하거나 이 저장소 옆에 두면 찾는다.

    SHOCKLENS_PATH=/path/to/shocklens
"""
import importlib
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]      # 저장소 폴더 (src/kfin_eval/bridges.py 기준)


def collatio(module):
    """Collatio의 모듈. 예: collatio('disclosure'), collatio('guard'), collatio('clients')"""
    return importlib.import_module(f"collatio.{module}")


def collatio_path():
    return _ROOT


def collatio_config():
    import yaml
    return yaml.safe_load((_ROOT / "config" / "experiment.yaml").read_text(encoding="utf-8"))


def _find_shocklens():
    cands = [os.environ.get("SHOCKLENS_PATH"), _ROOT.parent / "shocklens", Path.cwd().parent / "shocklens"]
    for c in cands:
        if c and (Path(c) / "engine" / "risk.py").exists():
            return Path(c).resolve()
    raise SystemExit("shocklens 저장소를 찾지 못했습니다. SHOCKLENS_PATH 환경변수로 위치를 지정하거나 "
                     "이 폴더 옆에 내려받으세요: git clone https://github.com/minyoungkang1227/shocklens.git")


def shocklens(module):
    """예: shocklens('risk'), shocklens('reverse')"""
    path = str(_find_shocklens())
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(f"engine.{module}")


def available():
    """{'collatio': True, 'shocklens': 있으면 True}. collatio는 같은 저장소라 항상 있다."""
    out = {"collatio": True}
    try:
        shocklens("risk")
        out["shocklens"] = True
    except (SystemExit, ImportError):
        out["shocklens"] = False
    return out
