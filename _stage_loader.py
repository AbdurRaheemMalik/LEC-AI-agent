"""
The one piece of "finding the correct files" plumbing this project needs
in code rather than prose: stage folders are named 01_planning,
02_execution, 03_synthesis, and Python identifiers can't start with a
digit, so `import 01_planning.run` isn't valid syntax. This loads each
stage's run.py directly by path instead.

Nothing here makes decisions - it just locates and loads the module a
stage's CONTEXT.md says should exist at <stage_dir>/run.py.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_stage(stage_dir: str) -> ModuleType:
    path = os.path.join(ROOT, stage_dir, "run.py")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"stage module not found at {path} (expected by CONTEXT.md for {stage_dir})")

    module_name = f"stage_{stage_dir}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
