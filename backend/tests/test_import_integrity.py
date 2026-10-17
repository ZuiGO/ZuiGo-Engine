"""Guards against dangling imports.

Most breakage from the big refactors was invisible because the imports live
inside functions (lazy) and the pipeline swallows stage exceptions: a module
imported fine at startup yet crashed whenever that code path actually ran.
These tests check *every* import statement in the backend, lazy ones included.
"""

import ast
import importlib
import pkgutil
import warnings
from pathlib import Path

import pytest

import backend

warnings.filterwarnings("ignore")

BACKEND_DIR = Path(list(backend.__path__)[0])
NON_TEST_MODULES = sorted(
    m.name
    for m in pkgutil.walk_packages(backend.__path__, "backend.")
    if ".tests." not in m.name and not m.name.endswith(".tests")
)


@pytest.mark.parametrize("module", NON_TEST_MODULES)
def test_module_imports_cleanly(module):
    importlib.import_module(module)


def _iter_backend_imports():
    for path in BACKEND_DIR.rglob("*.py"):
        if "tests" in path.relative_to(BACKEND_DIR).parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):  # ast.walk reaches imports nested in functions
            if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").startswith("backend"):
                yield path, node
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("backend"):
                        yield path, ast.ImportFrom(module=alias.name, names=[], level=0, lineno=node.lineno)


def test_every_backend_import_target_exists():
    problems = []
    for path, node in _iter_backend_imports():
        rel = path.relative_to(BACKEND_DIR.parent)
        try:
            mod = importlib.import_module(node.module)
        except Exception as e:
            problems.append(f"{rel}:{node.lineno} cannot import {node.module} ({type(e).__name__}: {e})")
            continue
        for alias in node.names:
            if alias.name == "*" or hasattr(mod, alias.name):
                continue
            try:
                importlib.import_module(f"{node.module}.{alias.name}")  # submodule
            except Exception:
                problems.append(f"{rel}:{node.lineno} {node.module} has no name '{alias.name}'")
    assert not problems, "dangling imports:\n" + "\n".join(problems)
