"""The first run, which is the only one most people judge the tool on.

The 4.6 review that prompted this said setup was unfriendly to a newcomer. The
guide exists to answer the three questions a first run actually raises: what
works, what to type, and whether what I typed took effect.
"""

import pytest

from airesearch import setup_guide
from airesearch.data.adapters.base import AdapterError


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A scratch settings file, so a test never reads the developer's own."""
    target = tmp_path / "research-profile.json"
    monkeypatch.setenv("AI_RESEARCH_PROFILE", str(target))
    return target


def _fake_chain(available=True, reason="not configured"):
    class _Adapter:
        name = "stub"

        def available(self):
            return available

        def unavailable_reason(self):
            return reason

    class _Chain:
        adapters = [_Adapter()]

    return _Chain()


def _patch_adapters(monkeypatch, *, available=True, fetch=None):
    from airesearch.data import adapters

    monkeypatch.setattr(adapters, "configure", lambda *a, **k: [])
    monkeypatch.setattr(adapters, "get_chain", lambda d: _fake_chain(available))
    monkeypatch.setattr(adapters, "fetch", fetch or (lambda d, k: [
        type("F", (), {"source": "stub"})()]))


# ── the output has to survive the console it is printed to ────────

def test_the_guide_is_ascii_only(profile, monkeypatch):
    """It is printed to whatever console the host has. A non-UTF-8 Windows
    terminal raises UnicodeEncodeError on anything else, which would make the
    setup guide itself the first crash."""
    _patch_adapters(monkeypatch, available=False)
    text = setup_guide.guide(verify=False)
    text.encode("ascii")          # raises if anything slipped in
    text.encode("cp1252")


# ── what it tells you ─────────────────────────────────────────────

def test_it_creates_the_settings_file_and_names_it(profile, monkeypatch):
    """Writing settings into the other candidate path is the single most common
    way to lose an hour here."""
    _patch_adapters(monkeypatch, available=False)
    assert not profile.exists()
    text = setup_guide.guide(verify=False)
    assert profile.exists()
    assert str(profile) in text


def test_a_missing_key_produces_the_exact_line_to_type(profile, monkeypatch):
    _patch_adapters(monkeypatch, available=False)
    text = setup_guide.guide(verify=True)
    assert '"sec_contact": "Jane Roe jane@example.com"' in text
    assert "fredaccount.stlouisfed.org" in text
    assert "To finish setup" in text


def test_a_working_domain_is_only_called_ready_after_it_answers(profile, monkeypatch):
    """Configured and working are different states, and the gap between them is
    where a wrong key hides."""
    _patch_adapters(monkeypatch, available=True)
    findings = {f["domain"]: f for f in setup_guide.check(verify=True)}
    assert findings["price"]["state"] == setup_guide.READY
    assert "came back from stub" in findings["price"]["detail"]


def test_a_source_that_is_configured_but_fails_is_not_ready(profile, monkeypatch):
    """A key that is present and wrong looks exactly like one that is right
    until something is actually fetched."""
    def _refuse(domain, key):
        raise AdapterError("403 Forbidden")

    _patch_adapters(monkeypatch, available=True, fetch=_refuse)
    findings = {f["domain"]: f for f in setup_guide.check(verify=True)}
    assert findings["us_equity"]["state"] == setup_guide.BROKEN
    assert "403" in findings["us_equity"]["detail"]


def test_verify_false_touches_no_network(profile, monkeypatch):
    """For an offline machine, and so the guide itself cannot hang."""
    def _explode(domain, key):
        raise AssertionError("fetch was called with verify=False")

    _patch_adapters(monkeypatch, available=True, fetch=_explode)
    states = {f["state"] for f in setup_guide.check(verify=False)}
    assert states == {setup_guide.SKIPPED}


def test_a_finished_setup_says_where_to_start(profile, monkeypatch):
    _patch_adapters(monkeypatch, available=True)
    text = setup_guide.guide(verify=True)
    assert "To finish setup" not in text
    assert "intake.md" in text
