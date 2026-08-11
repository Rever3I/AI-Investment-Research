"""Settings resolution, including the one that decides what language the user
reads their own research in.

The encoding cases are not hypothetical: this ships a Chinese-language release,
and the most likely thing a zh-CN Windows user does to this file is open it in
Notepad, which offers GBK ("ANSI") and UTF-8-with-BOM as ordinary save options.
Both used to break the feature they were editing.
"""

import json
import logging

import pytest

from skills._lib import config


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── defaults and merging ──────────────────────────────────────────

def test_defaults_apply_when_no_profile_exists(tmp_path):
    profile = config.load_profile(tmp_path / "absent.json")
    assert profile == dict(config.DEFAULTS)
    profile["output_language"] = "mutated"
    assert config.DEFAULTS["output_language"] == "en"  # callers cannot poison them


def test_defaults_cannot_be_mutated_in_place():
    with pytest.raises(TypeError):
        config.DEFAULTS["output_language"] = "de"


def test_settings_from_the_file_win(tmp_path):
    path = _write(tmp_path / "p.json", {"output_language": "zh-CN"})
    assert config.load_profile(path)["output_language"] == "zh-CN"


def test_absent_keys_fall_back_to_defaults(tmp_path):
    path = _write(tmp_path / "p.json", {"output_language": "zh-CN"})
    profile = config.load_profile(path)
    assert profile["sizing_method"] == config.DEFAULTS["sizing_method"]
    assert profile["debate_enabled"] == config.DEFAULTS["debate_enabled"]


# ── damaged files degrade, they do not raise ──────────────────────

def test_a_malformed_profile_falls_back_rather_than_raising(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert config.load_profile(path) == dict(config.DEFAULTS)


def test_an_empty_profile_falls_back(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("", encoding="utf-8")
    assert config.load_profile(path) == dict(config.DEFAULTS)


def test_a_non_object_profile_falls_back(tmp_path):
    path = _write(tmp_path / "p.json", ["not", "an", "object"])
    assert config.load_profile(path) == dict(config.DEFAULTS)


def test_a_profile_saved_in_a_legacy_chinese_codepage_falls_back(tmp_path):
    """Notepad's "ANSI" save on a zh-CN machine produces GBK. That must warn and
    degrade, not crash the pipeline on config load."""
    path = tmp_path / "p.json"
    path.write_bytes(
        json.dumps({"output_language": "中文"}, ensure_ascii=False).encode("gbk")
    )
    assert config.load_profile(path) == dict(config.DEFAULTS)


def test_a_profile_with_a_byte_order_mark_still_applies(tmp_path):
    """A BOM is what several CJK editors write by default. Ignoring it silently
    reverted the user's language to English."""
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"output_language": "zh-CN"}), encoding="utf-8-sig")
    assert config.output_language(path) == "zh-CN"


def test_a_profile_path_that_is_a_directory_falls_back(tmp_path):
    directory = tmp_path / "notafile"
    directory.mkdir()
    assert config.load_profile(directory) == dict(config.DEFAULTS)


# ── wrong types are rejected, not passed downstream ───────────────

def test_a_string_where_a_bool_belongs_is_rejected(tmp_path):
    # "false" is a truthy string: accepting it would enable the layer the user
    # was trying to switch off.
    path = _write(tmp_path / "p.json", {"debate_enabled": "false"})
    assert config.load_profile(path)["debate_enabled"] is False


def test_a_number_where_a_string_belongs_is_rejected(tmp_path):
    path = _write(tmp_path / "p.json", {"output_language": 123})
    assert config.output_language(path) == "en"


def test_an_object_where_a_string_belongs_is_rejected(tmp_path):
    path = _write(tmp_path / "p.json", {"output_language": {"a": 1}})
    assert config.output_language(path) == "en"


def test_a_null_value_falls_back_to_its_default(tmp_path):
    path = _write(tmp_path / "p.json", {"sizing_method": None})
    assert config.load_profile(path)["sizing_method"] == config.DEFAULTS["sizing_method"]


def test_a_bool_where_a_string_belongs_is_rejected(tmp_path):
    # bool is a subclass of int, and a naive isinstance check lets it through.
    path = _write(tmp_path / "p.json", {"output_language": True})
    assert config.output_language(path) == "en"


def test_wrong_types_are_warned_about(tmp_path, caplog):
    path = _write(tmp_path / "p.json", {"debate_enabled": "false"})
    with caplog.at_level(logging.WARNING):
        config.load_profile(path)
    assert any("debate_enabled" in r.getMessage() for r in caplog.records)


# ── typos are surfaced, not swallowed ─────────────────────────────

def test_a_misspelled_setting_is_dropped_and_warned_about(tmp_path, caplog):
    path = _write(tmp_path / "p.json", {"output_langauge": "zh-CN"})
    with caplog.at_level(logging.WARNING):
        profile = config.load_profile(path)
    assert "output_langauge" not in profile
    assert profile["output_language"] == "en"
    assert caplog.records, "a misspelled setting must not fail silently"


# ── output_language ───────────────────────────────────────────────

def test_output_language_defaults_to_english(tmp_path):
    assert config.output_language(tmp_path / "absent.json") == "en"


def test_output_language_accepts_any_tag(tmp_path):
    # No whitelist, for the same reason `market` has none: a hard-coded set of
    # supported languages is a restriction the user cannot configure away.
    for tag in ("zh-CN", "ja", "de", "pt-BR"):
        path = _write(tmp_path / f"{tag}.json", {"output_language": tag})
        assert config.output_language(path) == tag


@pytest.mark.parametrize("blank", ["", "   ", "\t\n", "  \r\n "])
def test_blank_output_language_falls_back_to_english(tmp_path, blank):
    path = _write(tmp_path / "p.json", {"output_language": blank})
    assert config.output_language(path) == "en"


def test_output_language_is_stripped(tmp_path):
    path = _write(tmp_path / "p.json", {"output_language": "  zh-CN  "})
    assert config.output_language(path) == "zh-CN"


# ── path resolution ───────────────────────────────────────────────

def test_env_var_selects_the_profile(monkeypatch, tmp_path):
    path = _write(tmp_path / "custom.json", {"output_language": "ja"})
    monkeypatch.setenv("AI_RESEARCH_PROFILE", str(path))
    assert config.output_language() == "ja"


def test_env_var_pointing_at_a_missing_file_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_RESEARCH_PROFILE", str(tmp_path / "nope.json"))
    assert config.output_language() == "en"


def test_explicit_path_beats_the_env_var(monkeypatch, tmp_path):
    env_file = _write(tmp_path / "env.json", {"output_language": "ja"})
    explicit = _write(tmp_path / "explicit.json", {"output_language": "de"})
    monkeypatch.setenv("AI_RESEARCH_PROFILE", str(env_file))
    assert config.output_language(explicit) == "de"


# ── the shipped file is the defaults ──────────────────────────────

def test_shipped_profile_matches_the_defaults_exactly():
    """Values, not just keys: a shipped file that disagrees with DEFAULTS means
    the READMEs document one thing and users get another."""
    from skills._lib.paths import default_profile_path

    shipped = json.loads(default_profile_path().read_text(encoding="utf-8-sig"))
    assert shipped == dict(config.DEFAULTS)


def test_shipped_sizing_method_is_one_the_storage_layer_accepts():
    from skills._lib.data.schema import SIZING_METHODS

    assert config.DEFAULTS["sizing_method"] in SIZING_METHODS


def test_a_round_number_is_accepted_for_a_float_setting(tmp_path):
    """JSON writes 0 and 1 without a decimal point, so a float setting arrives
    as an int whenever the user types a round number. Rejecting those sent
    position_cap: 0 back to a default of no cap at all."""
    path = _write(tmp_path / "p.json", {"position_cap": 0})
    assert config.load_profile(path)["position_cap"] == 0.0

    path = _write(tmp_path / "q.json", {"position_cap": 1})
    assert config.load_profile(path)["position_cap"] == 1.0


def test_a_float_setting_still_rejects_a_string(tmp_path):
    path = _write(tmp_path / "p.json", {"position_cap": "0.05"})
    assert config.load_profile(path)["position_cap"] == config.DEFAULTS["position_cap"]


def test_a_float_setting_rejects_a_bool(tmp_path):
    path = _write(tmp_path / "p.json", {"position_cap": True})
    assert config.load_profile(path)["position_cap"] == config.DEFAULTS["position_cap"]


def test_fixed_pct_has_a_value_behind_it():
    """Selecting sizing_method 'fixed_pct' used to crash: nothing in the profile
    carried the weight it needs."""
    assert isinstance(config.DEFAULTS["fixed_pct"], float)
    assert 0 < config.DEFAULTS["fixed_pct"] <= 1
