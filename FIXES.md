# Fixes

1. Agent files now saved to `artifacts/` after every trial - previously all deliverables were lost when the container exited
2. Python bytecode (`__pycache__`, `.pyc`, `.pyo`) excluded from artifact collection - only files the agent intentionally produced are kept
3. Removed `pass^k` metric; `mean_pass@k` now shows actual reward per run; `pass_at_k` populated in `result.json`
