"""The README's examples run as written, against the installed package."""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

README = Path(__file__).parent.parent / "README.md"
EXAMPLES = re.findall(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), re.DOTALL)


def test_the_readme_has_examples() -> None:
    assert len(EXAMPLES) >= 3


@pytest.mark.parametrize("example", EXAMPLES, ids=[f"example-{n}" for n in range(1, len(EXAMPLES) + 1)])
def test_a_readme_example_runs(example: str, monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("readme_example")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(example, str(README), "exec"), module.__dict__)
