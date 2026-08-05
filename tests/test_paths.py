"""Where this project's files land, across the ways the repo gets installed.

Both the database and the config file resolve through skills._lib.paths, so that
the two cannot disagree about what "the repo root" means. Getting this wrong is
quiet rather than loud: the data goes somewhere unwritable, or somewhere a
package upgrade deletes.
"""

from pathlib import Path

import pytest

from skills._lib import paths

RESOLVERS = {
    "db": (paths.default_db_path, paths.DB_ENV_VAR, Path("db") / "research.db"),
    "profile": (paths.default_profile_path, paths.PROFILE_ENV_VAR,
                Path("config") / "research-profile.json"),
}


@pytest.fixture(autouse=True)
def no_inherited_overrides(monkeypatch):
    monkeypatch.delenv(paths.DB_ENV_VAR, raising=False)
    monkeypatch.delenv(paths.PROFILE_ENV_VAR, raising=False)


@pytest.mark.parametrize("kind", sorted(RESOLVERS))
def test_env_override_wins(kind, monkeypatch, tmp_path):
    resolve, env_var, _ = RESOLVERS[kind]
    target = tmp_path / "elsewhere" / "mine.ext"
    monkeypatch.setenv(env_var, str(target))
    assert resolve() == target


@pytest.mark.parametrize("kind", sorted(RESOLVERS))
def test_env_override_expands_home(kind, monkeypatch):
    resolve, env_var, _ = RESOLVERS[kind]
    monkeypatch.setenv(env_var, "~/somewhere/mine.ext")
    assert resolve() == Path.home() / "somewhere" / "mine.ext"


@pytest.mark.parametrize("kind", sorted(RESOLVERS))
def test_source_checkout_keeps_files_in_the_repo(kind, monkeypatch, tmp_path):
    resolve, _, relative = RESOLVERS[kind]
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.setattr(paths, "_CHECKOUT_ROOT", checkout)

    assert resolve() == checkout / relative


@pytest.mark.parametrize("kind", sorted(RESOLVERS))
def test_installed_package_falls_back_to_a_user_directory(kind, monkeypatch, tmp_path):
    """Under a non-editable `pip install .` the package sits in site-packages,
    where a repo-relative path would try to write inside the install tree."""
    resolve, _, relative = RESOLVERS[kind]
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()  # no pyproject.toml, so this is an install not a checkout
    monkeypatch.setattr(paths, "_CHECKOUT_ROOT", site_packages)

    resolved = resolve()
    assert resolved == paths._USER_DIR / relative.name
    assert site_packages not in resolved.parents


@pytest.mark.parametrize("kind", sorted(RESOLVERS))
def test_this_checkout_resolves_into_the_repo(kind):
    resolve, _, relative = RESOLVERS[kind]
    repo_root = Path(__file__).resolve().parent.parent
    assert resolve() == repo_root / relative


def test_the_two_resolvers_agree_on_the_root():
    """The whole point of sharing this module: db and config must never disagree
    about whether this is a checkout or an install."""
    repo_root = Path(__file__).resolve().parent.parent
    assert paths.default_db_path().parent.parent == repo_root
    assert paths.default_profile_path().parent.parent == repo_root
