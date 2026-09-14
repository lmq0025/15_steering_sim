from importlib.metadata import version


def test_installed_distribution_metadata() -> None:
    assert version("steering-sim") == "0.1.0"

