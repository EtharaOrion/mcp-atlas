# rubric_pytest_kit — Channel A task-authoring templates

Templates for a task's `tests/test_outputs.py` + `tests/test_weights.json`,
graded by [`../weighted_judge.py`](../weighted_judge.py) using the assertion
helpers in [`../traj_asserts.py`](../traj_asserts.py).

## Quick start

1. Copy `templates/test_outputs.py` into the task's `tests/` dir and edit the
   tool names / arguments for the actual task.
2. Copy `templates/test_weights.example.json` alongside it as
   `test_weights.json`, and:
   - rename the test entries under `components.traj_tests.tests` to match
     your test function names, with a **positive** weight for goals and a
     **negative** weight for guards (see the polarity note below);
   - set `components.traj_tests.weight` to a non-zero value to actually opt
     the task into Channel A scoring — it defaults to `0` in the example so
     copying the file alone never silently changes a task's grade.
3. Leave `components.rubric` alone for now — Channel B wiring lands in a
   later phase; today only `traj_tests` is read.

## Guard-test polarity

Every assertion in `test_outputs.py` is phrased **positively** — "X
happened" — never `assert not ...`. Whether X happening is good or bad is
decided entirely by the *sign* of that test's weight in `test_weights.json`:

- **positive weight → goal test.** Passing earns credit.
- **negative weight → guard test.** Passing (the forbidden thing happened)
  earns a penalty. *Not* triggering earns nothing — a run that was never
  anywhere near the guard shouldn't score higher than one that avoided it on
  purpose.

This keeps a test's assertion body describing *what happened*, and keeps
*whether that's good or bad* entirely in the weights file, where it's easy
to audit and change without touching test logic.

## Scope

Channel A only inspects **which tools were called, with what arguments** —
never the content of the agent's final answer. Grading the answer's factual
content is Channel B's job (`tests/rubric.json` / `GTFA_CLAIMS`), scored
separately by [`../score_claims.py`](../score_claims.py).
