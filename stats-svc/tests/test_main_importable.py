"""Test that app.main is importable without uvicorn or asyncpg installed.

TDD: written before implementation.
"""


def test_app_main_importable_without_uvicorn_asyncpg():
    """Importing app.main must succeed even when uvicorn/asyncpg are absent.

    This verifies the lazy-import contract: uvicorn and asyncpg are only
    imported inside amain(), not at module level.
    """
    import sys

    # Temporarily hide uvicorn and asyncpg from imports
    _saved = {}
    for name in list(sys.modules.keys()):
        if name == "uvicorn" or name.startswith("uvicorn."):
            _saved[name] = sys.modules.pop(name)
        if name == "asyncpg" or name.startswith("asyncpg."):
            _saved[name] = sys.modules.pop(name)

    # Block them via sys.modules sentinel
    sys.modules["uvicorn"] = None  # type: ignore[assignment]
    sys.modules["asyncpg"] = None  # type: ignore[assignment]

    try:
        # Remove app.main if already cached from a previous import
        for name in list(sys.modules.keys()):
            if name == "app.main" or name.startswith("app.main."):
                del sys.modules[name]

        import app.main  # must not raise ImportError  # noqa: F401
        assert hasattr(app.main, "main"), "app.main must expose a main() entry point"
        assert hasattr(app.main, "amain"), "app.main must expose amain() coroutine"
    finally:
        # Restore modules
        del sys.modules["uvicorn"]
        del sys.modules["asyncpg"]
        sys.modules.update(_saved)
