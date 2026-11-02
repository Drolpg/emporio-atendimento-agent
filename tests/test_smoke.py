"""Smoke test: verify package imports and version is set."""


def test_emporio_imports():
    """Test that emporio can be imported."""
    import emporio  # noqa: F401


def test_emporio_has_version():
    """Test that emporio has a non-empty __version__."""
    import emporio

    assert hasattr(emporio, "__version__")
    assert isinstance(emporio.__version__, str)
    assert len(emporio.__version__) > 0
