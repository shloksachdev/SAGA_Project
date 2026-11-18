"""
Purpose: Enforcement test for D5: no static workload references or hardcoded service names.
Phase: Phase 5
"""

import ast
import os
import pytest

BANNED_NAMES = {
    "order",
    "payment",
    "inventory",
    "notification",
    "order_handler",
    "payment_handler",
    "inventory_handler",
    "notification_handler",
    "workloads",
}

TARGET_FILES = [
    os.path.join("common", "election.py"),
    os.path.join("common", "lease.py"),
    os.path.join("common", "orchestrator.py"),
]


def _collect_core_files():
    files = list(TARGET_FILES)
    core_dir = os.path.join("common", "core")
    if os.path.exists(core_dir):
        for f in os.listdir(core_dir):
            if f.endswith(".py"):
                files.append(os.path.join(core_dir, f))
    return files


@pytest.mark.parametrize("file_path", _collect_core_files())
def test_no_static_refs(file_path):
    """
    Statically checks using AST that common/election.py, common/lease.py,
    common/orchestrator.py, and common/core/* do not import or reference
    workloads or any hard-coded function names (Order, Payment, Inventory, Notification, etc.).
    """
    assert os.path.exists(file_path), f"File {file_path} does not exist"

    with open(file_path, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source, filename=file_path)

    violations = []

    for node in ast.walk(tree):
        # 1. Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                for banned in BANNED_NAMES:
                    if banned in alias.name.lower():
                        violations.append((node.lineno, f"import {alias.name} matches banned '{banned}'"))

        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for banned in BANNED_NAMES:
                if banned in mod.lower():
                    violations.append((node.lineno, f"from {mod} matches banned '{banned}'"))
            for alias in node.names:
                for banned in BANNED_NAMES:
                    if banned in alias.name.lower():
                        violations.append((node.lineno, f"imported name {alias.name} matches banned '{banned}'"))

        # 2. Check variable, function, class names
        elif isinstance(node, ast.Name):
            if node.id.lower() in BANNED_NAMES:
                violations.append((node.lineno, f"Identifier '{node.id}' matches banned name"))

        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if node.name.lower() in BANNED_NAMES:
                violations.append((node.lineno, f"Definition '{node.name}' matches banned name"))

        elif isinstance(node, ast.Attribute):
            if node.attr.lower() in BANNED_NAMES:
                violations.append((node.lineno, f"Attribute '{node.attr}' matches banned name"))

        # 3. Check string literals (excluding docstrings at module level if necessary)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value.strip().lower()
            for banned in BANNED_NAMES:
                # Disallow exact matches or direct usage as service/workload string literals
                if val == banned or f"saga.{banned}" in val:
                    violations.append((node.lineno, f"String literal '{node.value}' matches banned '{banned}'"))

    assert not violations, f"Static reference violations found in {file_path}:\n" + "\n".join(
        f"  Line {line}: {msg}" for line, msg in violations
    )
