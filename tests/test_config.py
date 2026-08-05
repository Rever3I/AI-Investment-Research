"""Settings resolution, including the one that decides what language the user
reads their own research in.
"""

import json

from skills._lib import config


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_defaults_apply_when_no_profile_exists(tmp_path):
    profile = config.load_profile(tmp_path / "absent.json")
    assert profile == config.DEFAULTS
    assert profile is not config.DEFAULTS  # callers must not mutate the defaults


def test_settings_from_the_file_win(tmp_path):
    path = _write(tmp_path / "p.json", {"output_language": "zh-CN"})
    assert config.load_profile(path)["output_language"] == "zh-CN"


def test_absent_keys_fall_back_to_defaults(tmp_path):
    path = _write(tmp_path / "p.json", {"output_language": "zh-CN"})
    profile = config.load_profile(path)
    assert profile["sizing_method"] == config.DEFAULTS["sizing_method"]
    assert profile["debate_enabled"] == config.DEFAULTS["debate_enabled"]


def test_a_malformed_profile_falls_back_rather_than_raising(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert config.load_profile(path) == config.DEFAULTS


def test_a_non_object_profile_falls_back(tmp_path):
    path = _write(tmp_path / "p.json", ["not", "an", "object"])
    assert config.load_profile(path) == config.DEFAULTS


def test_env_var_selects_the_profile(monkeypatch, tmp_path):
    path = _write(tmp_path / "custom.json", {"output_language": "ja"})
    monkeypatch.setenv("AI_RESEARCH_PROFILE", str(path))
    assert config.output_language() == "ja"


def test_output_language_defaults_to_english(tmp_path):
    assert config.output_language(tmp_path / "absent.json") == "en"


def test_output_language_accepts_any_tag(tmp_path):
    # No whitelist, for the same reason `market` has none: a hard-coded set of
    # supported languages is a restriction the user cannot configure away.
    for tag in ("zh-CN", "ja", "de", "pt-BR"):
        path = _write(tmp_path / f"{tag}.json", {"output_language": tag})
        assert config.output_language(path) == tag


def test_blank_output_language_falls_back_to_english(tmp_path):
    path = _write(tmp_path / "p.json", {"output_language": ""})
    assert config.output_language(path) == "en"


def test_shipped_profile_parses_and_covers_every_default():
    """The config file in the repo must stay in sync with DEFAULTS, or a user
    editing it finds settings that silently do nothing."""
    shipped = json.loads(config.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    assert set(shipped) == set(config.DEFAULTS)
