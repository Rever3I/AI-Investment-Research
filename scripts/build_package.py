#!/usr/bin/env python
"""Build a distributable skill package, in either language.

There are two front ends to this repo now. SKILL.md and the five stage guides
ship in Chinese, because a marketplace renders SKILL.md as the listing overview
and the Chinese listing was showing an English page. The English text is kept
under docs/ and swapped back in for the English package, so neither audience
gets the other one's file.

Zipping the skill directory by hand is what this replaces: it silently picks up
whichever language happens to be checked in, plus every .pyc compiled for the
builder's own Python.

    python scripts/build_package.py --lang zh --out "D:/downloads"
    python scripts/build_package.py --lang en --out "D:/downloads"

SKILL.md sits at the archive root, so extracting gives a working skill folder
whichever shape the importer expects.
"""

import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "investment-research"

# The English originals, kept beside the repo rather than inside the skill so
# nothing scanning the skill folder for *.md picks up two SKILL files.
EN_SKILL = REPO / "docs" / "SKILL.en.md"
EN_REFERENCES = REPO / "docs" / "references-en"

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".git"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}

# Marketplaces validate uploads by file type and reject the whole archive on
# one unknown entry. A `.gitkeep` left in a directory that had since filled up
# with real files failed a SkillHub upload, so the check moved to build time:
# a rejection here names the file, where a rejection at upload names a path
# inside a zip nobody has opened.
ALLOWED_SUFFIXES = {".py", ".md", ".json", ".txt", ".yaml", ".yml", ".toml"}

DEFAULT_NAMES = {"en": "HF-Stock-Analysis-Pro", "zh": "investment-research-zh"}


def version() -> str:
    """Read it from pyproject rather than repeating it here.

    tomllib is 3.11 and this project targets 3.10 with no dependencies, so the
    line is matched instead of parsed. A version that disagrees with the package
    metadata is worse than no version in the filename at all.
    """
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.M)
    if not match:
        raise SystemExit("pyproject.toml has no version line to stamp")
    return match.group(1)


def keep(relative: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in relative.parts):
        return False
    # Dotfiles are repository plumbing. None of them mean anything to someone
    # who installed the skill, and some of them fail the upload.
    if relative.name.startswith("."):
        return False
    return relative.suffix not in EXCLUDE_SUFFIXES


def check_types(stage: Path) -> None:
    """Refuse to write an archive a marketplace will reject."""
    rejected = sorted(
        str(p.relative_to(stage))
        for p in stage.rglob("*")
        if p.is_file() and p.suffix.lower() not in ALLOWED_SUFFIXES
    )
    if rejected:
        listed = "\n  ".join(rejected)
        raise SystemExit(
            "these files have a type marketplaces reject; rename or exclude "
            f"them before publishing:\n  {listed}"
        )


def stage_skill(stage: Path) -> int:
    copied = 0
    for src in sorted(SKILL.rglob("*")):
        relative = src.relative_to(SKILL)
        if not keep(relative):
            continue
        dest = stage / relative
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
    return copied


def swap_to_english(stage: Path) -> None:
    missing = [p for p in (EN_SKILL, EN_REFERENCES) if not p.exists()]
    if missing:
        raise SystemExit(
            "cannot build the English package, these are missing: "
            + ", ".join(str(p.relative_to(REPO)) for p in missing)
        )
    shutil.copy2(EN_SKILL, stage / "SKILL.md")
    for guide in EN_REFERENCES.glob("*.md"):
        shutil.copy2(guide, stage / "references" / guide.name)

    # A guide the Chinese side has and the English side does not would ship as
    # a Chinese file inside the English package, which is the exact mixing this
    # script exists to prevent.
    zh_guides = {p.name for p in (SKILL / "references").glob("*.md")}
    en_guides = {p.name for p in EN_REFERENCES.glob("*.md")}
    if zh_guides != en_guides:
        raise SystemExit(
            f"the two guide sets differ: only in zh {sorted(zh_guides - en_guides)}, "
            f"only in en {sorted(en_guides - zh_guides)}"
        )


def write_example_profile(stage: Path, lang: str) -> None:
    """Ship a filled-in profile beside the skill.

    ensure_profile() creates the real one at runtime, but a reader deciding
    whether to buy this wants to see the settings without installing it first.
    """
    sys.path.insert(0, str(SKILL))
    from airesearch import config  # noqa: PLC0415 - needs the path set above

    example = dict(config.DEFAULTS)
    example["sec_contact"] = "Your Name you@example.com"
    if lang == "zh":
        example["output_language"] = "zh-CN"
    (stage / "research-profile.example.json").write_text(
        json.dumps(example, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    parser.add_argument("--out", default=str(REPO / "dist"),
                        help="directory to write the .zip into")
    parser.add_argument("--name", default=None, help="archive base name")
    args = parser.parse_args()

    stage = REPO / "build" / f"package-{args.lang}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    copied = stage_skill(stage)
    if args.lang == "en":
        swap_to_english(stage)

    # As LICENSE.txt: an extensionless file is the same upload trap, and
    # GitHub still reads the repository's own LICENSE for its badge.
    shutil.copy2(REPO / "LICENSE", stage / "LICENSE.txt")
    shutil.copy2(REPO / ("README.en.md" if args.lang == "en" else "README.md"),
                 stage / "README.md")
    write_example_profile(stage, args.lang)
    check_types(stage)

    name = args.name or DEFAULT_NAMES[args.lang]
    out = Path(args.out) / f"{name}-v{version()}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(stage).as_posix())

    # Printed with the path last so a console that cannot encode it still shows
    # the counts. Windows consoles default to cp1252 and raise on a CJK path.
    print(f"lang={args.lang}  skill files={copied}  "
          f"size={out.stat().st_size / 1024:.0f}KB")
    print(f"wrote {out.name} to {out.parent}")


if __name__ == "__main__":
    main()
