"""The installed package."""
import event_connect


def test_the_version_is_the_installed_packages() -> None:
    assert event_connect.__version__


def test_everything_exported_exists() -> None:
    for name in event_connect.__all__:
        assert hasattr(event_connect, name), name
