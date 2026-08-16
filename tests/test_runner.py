import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("run_model", ROOT / "run_model.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_frozen_parser_routes_without_substantive_repair():
    direct, route, error = MODULE.parse_model_output('{"choice":"A","confidence":70}')
    assert direct == {"choice": "A", "confidence": 70}
    assert route == "direct_json"
    assert not error

    fenced, route, error = MODULE.parse_model_output('```json\n{"choice":"uncertain","confidence":40}\n```')
    assert fenced == {"choice": "uncertain", "confidence": 40}
    assert route == "outer_code_fence"
    assert not error

    embedded, route, error = MODULE.parse_model_output('Result: {"choice":"B","confidence":51} trailing prose')
    assert embedded == {"choice": "B", "confidence": 51}
    assert route == "first_braced_object"
    assert not error

    invalid, route, error = MODULE.parse_model_output("{'choice':'A','confidence':70}")
    assert invalid is None
    assert route is None
    assert "no valid JSON" in error


def test_brace_parser_respects_quoted_braces():
    text = 'prefix {"note":"a } brace", "choice":"A","confidence":50} suffix'
    assert MODULE.first_braced_object(text) == ('{"note":"a } brace", "choice":"A","confidence":50}')
