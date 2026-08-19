"""Where this project's files land, across the ways the repo gets installed.

Both the database and the config file resolve through airesearch.paths, so that
the two cannot disagree about what "the repo root" means. Getting this wrong is
quiet rather than loud: the data goes somewhere unwritable, or somewhere a
package upgrade deletes.
"""

from pathlib import Path

import pytest

from airesearch import paths

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
    # Pin both user directories: the developer's real home may hold one from an
    # install under the project's previous name, and the fallback would then
    # resolve somewhere this test did not choose.
    monkeypatch.setattr(paths, "_USER_DIR", tmp_path / ".ai-portfolio-manager")
    monkeypatch.setattr(paths, "_LEGACY_USER_DIR", tmp_path / ".ai-investment-research")

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


# ── the rename must not strand an existing install ────────────────

def test_the_directory_from_the_old_name_is_used_when_it_is_the_one_in_use(
        monkeypatch, tmp_path):
    """Renaming the project moves the per-user directory. Anyone who installed
    under the old name has their profile and database there, and switching
    without looking would bring the pipeline back up on defaults with an empty
    history and no sign anything was lost."""
    from airesearch import paths

    legacy = tmp_path / ".ai-investment-research"
    legacy.mkdir()
    monkeypatch.setattr(paths, "_USER_DIR", tmp_path / ".ai-portfolio-manager")
    monkeypatch.setattr(paths, "_LEGACY_USER_DIR", legacy)
    monkeypatch.delenv(paths.DB_ENV_VAR, raising=False)
    monkeypatch.setattr(paths, "_is_source_checkout", lambda root: False)

    assert paths.default_db_path().parent == legacy
    assert paths.default_profile_path().parent == legacy


def test_the_new_directory_wins_once_it_exists(monkeypatch, tmp_path):
    """Both present means the user has moved on; the old one is leftovers."""
    from airesearch import paths

    legacy = tmp_path / ".ai-investment-research"
    current = tmp_path / ".ai-portfolio-manager"
    legacy.mkdir()
    current.mkdir()
    monkeypatch.setattr(paths, "_USER_DIR", current)
    monkeypatch.setattr(paths, "_LEGACY_USER_DIR", legacy)
    monkeypatch.delenv(paths.DB_ENV_VAR, raising=False)
    monkeypatch.setattr(paths, "_is_source_checkout", lambda root: False)

    assert paths.default_db_path().parent == current


def test_a_fresh_install_uses_the_current_name(monkeypatch, tmp_path):
    from airesearch import paths

    monkeypatch.setattr(paths, "_USER_DIR", tmp_path / ".ai-portfolio-manager")
    monkeypatch.setattr(paths, "_LEGACY_USER_DIR", tmp_path / ".ai-investment-research")
    monkeypatch.delenv(paths.DB_ENV_VAR, raising=False)
    monkeypatch.setattr(paths, "_is_source_checkout", lambda root: False)

    assert paths.default_db_path().parent.name == ".ai-portfolio-manager"
