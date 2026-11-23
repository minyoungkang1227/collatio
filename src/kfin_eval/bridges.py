"""다른 저장소 연결. EchoGuard(거르기)와 ShockLens(정답 계산)의 코드를 그대로 불러 쓴다.

복사하지 않고 불러 쓰는 이유: 원본이 바뀌면 여기도 같이 바뀌어야 하기 때문이다.
저장소 위치는 환경변수로 지정하거나, 이 프로젝트 폴더 옆에 두면 자동으로 찾는다.

    COLLATIO_PATH=/path/to/collatio   SHOCKLENS_PATH=/path/to/shocklens   (옛 이름 ECHOGUARD_PATH도 받는다)
"""
import importlib
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _find(env, name, marker):
    cands = [os.environ.get(env), _ROOT.parent / name, _ROOT / name, Path.cwd().parent / name]
    for c in cands:
        if c and (Path(c) / marker).exists():
            return Path(c).resolve()
    raise SystemExit(f"{name} 저장소를 찾지 못했습니다. {env} 환경변수로 위치를 지정하거나 "
                     f"이 폴더 옆에 내려받으세요: git clone https://github.com/minyoungkang1227/{name}.git")


def _use(path):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _collatio():
    """(저장소 폴더, 패키지 이름). 2026-11-22에 EchoGuard가 Collatio로 이름을 바꿨다. 두 이름을 모두 찾는다."""
    here = [_ROOT.parent, _ROOT, Path.cwd().parent]
    cands = [os.environ.get("COLLATIO_PATH"), os.environ.get("ECHOGUARD_PATH")]
    cands += [base / name for name in ("collatio", "echoguard") for base in here]
    for c in cands:
        for pkg in ("collatio", "echoguard"):      # 폴더 이름과 패키지 이름이 서로 달라도 된다
            if c and (Path(c) / "src" / pkg / "guard.py").exists():
                return Path(c).resolve(), pkg
    raise SystemExit("Collatio(옛 이름 EchoGuard) 저장소를 찾지 못했습니다. COLLATIO_PATH 환경변수로 위치를 지정하거나 "
                     "이 폴더 옆에 내려받으세요: git clone https://github.com/minyoungkang1227/collatio.git")


def echoguard_path():
    return _collatio()[0]


def echoguard(module):
    """Collatio(옛 EchoGuard)의 모듈. 예: echoguard('disclosure'), echoguard('guard'), echoguard('clients')"""
    path, pkg = _collatio()
    _use(path / "src")
    return importlib.import_module(f"{pkg}.{module}")


def echoguard_config():
    import yaml
    return yaml.safe_load((echoguard_path() / "config" / "experiment.yaml").read_text(encoding="utf-8"))


def shocklens(module):
    """예: shocklens('risk'), shocklens('reverse')"""
    _use(_find("SHOCKLENS_PATH", "shocklens", "engine/risk.py"))
    return importlib.import_module(f"engine.{module}")


def available():
    out = {}
    for name, fn in (("echoguard", lambda: echoguard("guard")), ("shocklens", lambda: shocklens("risk"))):
        try:
            fn()
            out[name] = True
        except (SystemExit, ImportError):
            out[name] = False
    return out
