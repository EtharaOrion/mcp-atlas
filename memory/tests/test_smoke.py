"""Smoke test: prove the engram package imports and exposes its module surface.

This test is a scaffold-time sanity check. It does not exercise any
Bucket-D accepting path.
"""

from __future__ import annotations


def test_package_imports() -> None:
    import engram

    assert engram.__version__ == "0.1.0"


def test_module_surface() -> None:
    import engram

    expected = {
        "recon",
        "ingestor",
        "verifier",
        "freshener",
        "reporter",
        "projector",
        "provenance",
        "checkpointer",
        "recovery",
        "canary",
        "fidelity",
        "calibration",
        "researcher",
        "genesis",
    }
    assert set(engram.__all__) == expected


def test_submodules_importable() -> None:
    from engram import (
        calibration,
        canary,
        checkpointer,
        fidelity,
        freshener,
        genesis,
        ingestor,
        projector,
        provenance,
        recon,
        recovery,
        reporter,
        researcher,
        verifier,
    )

    for module in (
        recon,
        ingestor,
        verifier,
        freshener,
        reporter,
        projector,
        provenance,
        checkpointer,
        recovery,
        canary,
        fidelity,
        calibration,
        researcher,
        genesis,
    ):
        assert module is not None
