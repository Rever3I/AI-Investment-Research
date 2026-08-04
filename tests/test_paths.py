"""Where the database lands, across the ways this repo gets installed.

Both storage layers share one database file, and both resolve it through
skills._lib.paths. Getting that wrong is quiet rather than loud: the data goes
somewhere unwritable, or somewhere a package upgrade deletes.
"""

from pathlib import Path

from skills._lib import paths


def test_env_override_wins(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere" / "mine.db"
    monkeypatch.setenv("AI_RESEARCH_DB", str(target))
    assert paths.default_db_path() == target


def test_env_override_expands_home(monkeypatch):
    monkeypatch.setenv("AI_RESEARCH_DB", "~/somewhere/research.db")
    assert paths.default_db_path() == Path.home() / "somewhere" / "research.db"


def test_source_checkout_keeps_the_database_in_the_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_RESEARCH_DB", raising=False)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.setattr(paths, "_CHECKOUT_ROOT", checkout)

    assert paths.default_db_path() == checkout / "db" / "research.db"


def test_installed_package_falls_back_to_a_user_directory(monkeypatch, tmp_path):
    """Under a non-editable `pip install .` the package sits in site-packages,
    where a repo-relative path would try to write inside the install tree."""
    monkeypatch.delenv("AI_RESEARCH_DB", raising=False)
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()  # no pyproject.toml — this is an install, not a checkout
    monkeypatch.setattr(paths, "_CHECKOUT_ROOT", site_packages)

    resolved = paths.default_db_path()
    assert resolved == paths._USER_FALLBACK
    assert site_packages not in resolved.parents


def test_this_checkout_resolves_into_the_repo():
    repo_root = Path(__file__).resolve().parent.parent
    assert paths.default_db_path() == repo_root / "db" / "research.db"
