"""The stage guides are translated. The literal values inside them are not.

Several fields are matched literally by a later stage or validated against a
fixed set, so a guide that translates one does not fail loudly — it fails months
later when nothing matches. Translating the guides is exactly the moment that
becomes easy to do by accident, which is why it is checked rather than trusted.

These assert on the guide text an agent actually reads, not on the English
originals kept under docs/references-en/.
"""

import re
from pathlib import Path

import pytest

from airesearch.data.schema import DEBATE_MODES, DIFF_VERDICTS, ENTRY_PATHS, SIZING_METHODS

_GUIDES = Path(__file__).resolve().parent.parent / "skills" / "investment-research" / "references"

# Each guide must still carry the literal tokens the pipeline matches on.
_REQUIRED = {
    "intake.md": ENTRY_PATHS,
    "portfolio.md": SIZING_METHODS,
    "sellcheck.md": DIFF_VERDICTS,
    "valuation.md": DEBATE_MODES + ("bull", "base", "bear"),
}


def _text(name):
    return (_GUIDES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name,tokens", sorted(_REQUIRED.items()))
def test_the_literal_values_survive_translation(name, tokens):
    text = _text(name)
    for token in tokens:
        assert token in text, (
            f"{name} no longer contains the literal `{token}`. A stage that "
            f"validates against it would reject whatever the guide taught "
            f"instead."
        )


@pytest.mark.parametrize("path", sorted(_GUIDES.glob("*.md")), ids=lambda p: p.name)
def test_no_guide_still_points_at_a_skill_that_no_longer_exists(path):
    """The five stages were once five separate skills. A guide telling the agent
    to "run research-thesis, a separate skill" now names something uninstallable,
    and the agent has no way to discover that from inside the run."""
    stale = re.findall(r"research-(?:intake|thesis|valuation|portfolio|sellcheck)",
                       path.read_text(encoding="utf-8"))
    assert not stale, f"{path.name} refers to the retired skill names: {sorted(set(stale))}"


@pytest.mark.parametrize("path", sorted(_GUIDES.glob("*.md")), ids=lambda p: p.name)
def test_no_stray_characters_from_another_script(path):
    """Caught a Cyrillic fragment mid-sentence in a hand-translated guide. It
    renders as a plausible-looking word and nothing else would flag it."""
    strays = re.findall(r"[Ѐ-ӿ؀-ۿ฀-๿]+",
                        path.read_text(encoding="utf-8"))
    assert not strays, f"{path.name} contains non-CJK, non-Latin fragments: {strays}"


def test_every_stage_named_in_skill_md_has_its_guide():
    skill = (_GUIDES.parent / "SKILL.md").read_text(encoding="utf-8")
    named = set(re.findall(r"references/(\w+)\.md", skill))
    on_disk = {p.stem for p in _GUIDES.glob("*.md")}
    assert named == on_disk, (
        f"SKILL.md routes to {sorted(named)} but the guides on disk are "
        f"{sorted(on_disk)}"
    )
