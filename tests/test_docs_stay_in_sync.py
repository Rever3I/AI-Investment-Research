"""Keep the two READMEs from drifting apart.

Translated docs rot quietly: someone edits the English, the Chinese keeps
describing last month's behaviour, and the reader who trusted it is the one who
gets hurt. These checks catch the two ways that starts — a setting documented in
one language but not the other, and a documented setting that no longer exists.
"""

from pathlib import Path

import pytest

from skills._lib import config

_REPO = Path(__file__).resolve().parent.parent
_READMES = {
    "en": _REPO / "README.md",
    "zh-CN": _REPO / "README.zh-CN.md",
}


@pytest.mark.parametrize("lang,path", _READMES.items())
@pytest.mark.parametrize("setting", sorted(config.DEFAULTS))
def test_every_setting_is_documented(lang, path, setting):
    assert setting in path.read_text(encoding="utf-8"), (
        f"{path.name} does not mention the `{setting}` setting"
    )


@pytest.mark.parametrize("lang,path", _READMES.items())
def test_every_layer_is_listed(lang, path):
    text = path.read_text(encoding="utf-8")
    for layer in ("research-intake", "research-thesis", "research-valuation",
                  "research-debate", "research-portfolio", "research-sellcheck"):
        assert layer in text, f"{path.name} does not list the {layer} layer"


@pytest.mark.parametrize("lang,path", _READMES.items())
def test_each_readme_links_to_the_other(lang, path):
    text = path.read_text(encoding="utf-8")
    other = "README.zh-CN.md" if lang == "en" else "README.md"
    assert other in text, f"{path.name} has no link to {other}"


@pytest.mark.parametrize("lang,path", _READMES.items())
def test_env_var_overrides_are_documented(lang, path):
    text = path.read_text(encoding="utf-8")
    for var in ("AI_RESEARCH_DB", "AI_RESEARCH_PROFILE"):
        assert var in text, f"{path.name} does not document {var}"
