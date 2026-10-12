"""Load the just-built module explicitly, bypassing editable wheel redirects."""

import importlib.util
import sys
from pathlib import Path

import pytest

module_path = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location("_matchup", module_path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.modules["_matchup"] = module
assert Path(module.__file__).resolve() == module_path
print(f"Native parity module: {module_path}")
raise SystemExit(pytest.main(["-q", sys.argv[2]]))
