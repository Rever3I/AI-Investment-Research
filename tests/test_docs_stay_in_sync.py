"""Keep the two READMEs from drifting apart.

Translated docs rot quietly: someone edits the English, the Chinese keeps
describing last month's behaviour, and the reader who trusted it is the one who
gets hurt.

These checks deliberately do not settle for `"output_language" in text`. Every
setting name already appears inside each README's JSON example, so a bare
substring check stays green even if the entire prose explanation is deleted —
which is exactly the drift being guarded against. Instead each setting must have
its own documentation line, and the JSON block must parse and match the defaults.
"""

import json
import re
from pathlib import Path

import pytest

from airesearch import config
from airesearch.data.schema import SIZING_METHODS

_REPO = Path(__file__).resolve().parent.parent
_READMES = {
    "en": _REPO / "README.md",
    "zh-CN": _REPO / "README.zh-CN.md",
}
# The stage guides on disk, so adding or merging one cannot leave the READMEs
# describing a shape the repo no longer has.
_LAYERS = tuple(sorted(
    p.stem for p in (_REPO / "skills" / "investment-research" / "references").glob("*.md")
))


def _text(path):
    return path.read_text(encoding="utf-8")


def _json_blocks(text):
    return re.findall(r"```json\n(.*?)```", text, flags=re.DOTALL)


@pytest.mark.parametrize("lang,path", sorted(_READMES.items()))
@pytest.mark.parametrize("setting", sorted(config.DEFAULTS))
def test_every_setting_has_its_own_documentation_line(lang, path, setting):
    """A bullet starting with the setting name, not merely a mention of it."""
    documented = re.search(rf"^-\s+`{re.escape(setting)}`", _text(path), flags=re.M)
    assert documented, (
        f"{path.name} has no `- \\`{setting}\\`` documentation line; a mention "
        f"inside the JSON example does not count"
    )


@pytest.mark.parametrize("lang,path", sorted(_READMES.items()))
def test_the_documented_example_config_matches_the_defaults(lang, path):
    blocks = _json_blocks(_text(path))
    assert blocks, f"{path.name} has no ```json example of the profile"
    parsed = [json.loads(b) for b in blocks]
    assert any(p == dict(config.DEFAULTS) for p in parsed), (
        f"{path.name}'s JSON example does not match DEFAULTS "
        f"({config.DEFAULTS!r}); a reader would configure the wrong thing"
    )


@pytest.mark.parametrize("lang,path", sorted(_READMES.items()))
def test_every_sizing_method_the_schema_accepts_is_listed(lang, path):
    text = _text(path)
    for method in SIZING_METHODS:
        assert method in text, (
            f"{path.name} does not list the `{method}` sizing method, which "
            f"schema.SIZING_METHODS accepts"
        )


@pytest.mark.parametrize("lang,path", sorted(_READMES.items()))
def test_every_layer_is_listed(lang, path):
    text = _text(path)
    for layer in _LAYERS:
        assert layer.lower() in text.lower(), (
            f"{path.name} does not mention the {layer} stage"
        )


@pytest.mark.parametrize("lang,path", sorted(_READMES.items()))
def test_each_readme_links_to_the_other(lang, path):
    other = "README.zh-CN.md" if lang == "en" else "README.md"
    assert other in _text(path), f"{path.name} has no link to {other}"


@pytest.mark.parametrize("lang,path", sorted(_READMES.items()))
def test_env_var_overrides_are_documented(lang, path):
    text = _text(path)
    for var in ("AI_RESEARCH_DB", "AI_RESEARCH_PROFILE"):
        assert var in text, f"{path.name} does not document {var}"


@pytest.mark.parametrize("lang,path", sorted(_READMES.items()))
def test_the_clone_url_is_identical_in_both(lang, path):
    """Two casings of the same URL is two canonical repos to anything that
    compares the string."""
    urls = set(re.findall(r"https://github\.com/\S+?\.git", _text(path)))
    assert urls == {"https://github.com/Rever3I/ai-investment-research.git"}, (
        f"{path.name} clone URL(s) {urls} differ from the canonical one"
    )
