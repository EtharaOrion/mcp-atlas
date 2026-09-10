"""FAILURE_CLASSES must name exactly what classify_failure can return.

The histogram in pass@N.json is seeded from FAILURE_CLASSES, so the tuple is
the published shape of that document. Nothing at runtime compares it against
classify_failure -- a class added to the function and not to the tuple would
still be counted (the increment uses .get), it would just never appear at 0,
which is the absent-vs-zero ambiguity the seeding exists to remove. This test
is the only thing holding the two together.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SOURCE = REPO / "tools" / "delivery" / "harbor_to_output.py"


def _returned_classes() -> set[str]:
    """The first element of every `return "...", ...` in classify_failure."""
    tree = ast.parse(SOURCE.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "classify_failure")
    found = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Tuple):
            continue
        head = node.value.elts[0]
        assert isinstance(head, ast.Constant) and isinstance(head.value, str), (
            f"classify_failure returns a non-literal class at line {node.lineno}; "
            "the tuple can no longer be checked statically"
        )
        found.add(head.value)
    return found


def _declared_classes() -> tuple[str, ...]:
    tree = ast.parse(SOURCE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "FAILURE_CLASSES" for t in node.targets
        ):
            return tuple(e.value for e in node.value.elts)
    raise AssertionError("FAILURE_CLASSES not found in harbor_to_output.py")


def test_declared_matches_returned():
    declared, returned = _declared_classes(), _returned_classes()
    assert set(declared) == returned, (
        f"missing from FAILURE_CLASSES: {sorted(returned - set(declared))}; "
        f"declared but unreachable: {sorted(set(declared) - returned)}"
    )


def test_no_duplicates():
    declared = _declared_classes()
    assert len(declared) == len(set(declared))
