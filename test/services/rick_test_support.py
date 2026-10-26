"""Offline test isolation: never import the real configuration or call providers."""

import ast
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import socket
import sys
import types
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def offline_context():
    stack = ExitStack()
    fake_config = types.ModuleType("app.config")
    fake_config.config = types.SimpleNamespace(app={}, ui={}, whisper={}, proxy={})
    stack.enter_context(patch.dict(sys.modules, {"app.config": fake_config}))
    stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")))
    stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")))
    return stack


def load_module(relative_path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_functions(relative_path, names, namespace):
    """Execute real function bodies without UI startup/config/provider imports."""
    source = ROOT / relative_path
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in selected} != set(names):
        raise AssertionError("Missing function under test")
    for node in selected:
        node.decorator_list = []
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, *selected], type_ignores=[]))
    exec(compile(module, str(source), "exec"), namespace)
    return types.SimpleNamespace(**namespace)
