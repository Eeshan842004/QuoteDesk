"""QuoteDesk synthetic data generation (ground-truth-first)."""
import sys as _sys
from pathlib import Path as _Path

# the shared library lives in eval/evallib; make `import evallib` work for every datagen module
_EVAL = str(_Path(__file__).resolve().parents[1] / "eval")
if _EVAL not in _sys.path:
    _sys.path.insert(0, _EVAL)
