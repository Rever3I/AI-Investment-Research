#!/usr/bin/env python
"""A first run that says what works, what does not, and exactly what to write.

`status_report` answers "is this adapter configured". That is not the question
someone has on their first run. Theirs is "why did nothing happen, and what do I
type" — and a report built from config presence cannot answer it, because a key
that is present and wrong looks identical to one that is right.

So this does three things `status_report` does not:

* **Proves it.** Where a source needs nothing, it fetches something real. A
  domain marked ready here has answered, not merely been configured.
* **Names the file.** Settings live in a path that depends on the install, and
  the single most common way to lose an hour is to write them into the other
  one. The profile is created if absent and its resolved path is printed.
* **Says what to type.** Not "sec_contact is missing" but which key, in which
  file, in what shape, and where the value comes from.

Output is ASCII only. This gets printed to whatever console the host happens to
have, and a non-UTF-8 Windows terminal raises UnicodeEncodeError on anything
else, which would turn the setup guide itself into the first crash.
"""

import logging

from .config import ensure_profile, load_profile
from .paths import default_db_path

_log = logging.getLogger(__name__)

READY, MISSING, BROKEN, SKIPPED = "ready", "missing", "broken", "skipped"

# One probe per domain, chosen to be cheap and stable: a mega-cap that will not
# be delisted, and for China a name every data source carries.
_PROBES = {
    "price": ("AAPL", "a quote"),
    "us_equity": ("AAPL", "owner-earnings inputs"),
    "cn_equity": ("600519", "owner-earnings inputs"),
    "macro": ("DGS10", "the 10-year yield"),
}

_SETTINGS = {
    "us_equity": {
        "key": "sec_contact",
        "example": '"Jane Roe jane@example.com"',
        "why": "SEC requires a name and email in the User-Agent and returns 403 "
               "without one.",
        "where": "Any real name and email you are willing to identify yourself "
                 "to the SEC with.",
    },
    "macro": {
        "key": "fred_api_key",
        "example": '"abcdef1234567890abcdef1234567890"',
        "why": "FRED supplies the risk-free rate that gives a discount rate its "
               "provenance.",
        "where": "Free, instant: https://fredaccount.stlouisfed.org/apikeys",
    },
}


def check(verify: bool = True) -> list:
    """One record per domain: what it is, whether it works, and what is missing.

    `verify=False` skips every network call, for a machine that is offline or a
    caller that only wants the configuration read.
    """
    from .data.adapters import configure, fetch, get_chain

    profile = load_profile()
    configure(profile)

    findings = []
    for domain in sorted(_PROBES):
        key, describes = _PROBES[domain]
        setting = _SETTINGS.get(domain)
        try:
            chain = get_chain(domain)
        except Exception as exc:                     # noqa: BLE001 - reported
            findings.append({"domain": domain, "state": BROKEN,
                             "detail": f"no adapter chain registered ({exc})"})
            continue

        unavailable = [a for a in chain.adapters if not a.available()]
        if len(unavailable) == len(chain.adapters):
            # The adapter's own reason repeats the file path and the fix, which
            # the block below states properly. Here it would be said three times.
            detail = ("not configured, see below" if setting
                      else unavailable[0].unavailable_reason())
            findings.append({
                "domain": domain,
                "state": MISSING if setting else BROKEN,
                "setting": setting,
                "detail": detail,
            })
            continue

        if not verify:
            findings.append({"domain": domain, "state": SKIPPED, "setting": setting,
                             "detail": "not checked (verify=False)"})
            continue

        try:
            facts = fetch(domain, key)
        except Exception as exc:                     # noqa: BLE001 - reported
            findings.append({"domain": domain, "state": BROKEN, "setting": setting,
                             "detail": f"{describes} for {key} did not arrive: {exc}"})
            continue

        source = facts[0].source if facts else "?"
        findings.append({"domain": domain, "state": READY,
                         "detail": f"{describes} for {key} came back from {source}"})
    return findings


def guide(verify: bool = True) -> str:
    """The whole first run as one printable page."""
    settings_file = ensure_profile()
    findings = check(verify=verify)

    lines = ["Setup check", "=" * 60, "",
             f"Settings : {settings_file}",
             f"Records  : {default_db_path()}", ""]

    ready = [f for f in findings if f["state"] == READY]
    lines.append(f"{len(ready)} of {len(findings)} data domains answered." if verify
                 else "Configuration read; nothing was fetched.")
    lines.append("")

    for finding in findings:
        mark = {READY: "[OK]  ", MISSING: "[SET] ",
                BROKEN: "[FAIL]", SKIPPED: "[--]  "}[finding["state"]]
        lines.append(f"{mark} {finding['domain']:<11} {finding['detail']}")

    todo = [f for f in findings if f["state"] in (MISSING, BROKEN) and f.get("setting")]
    if todo:
        lines += ["", "To finish setup", "-" * 60,
                  f"Open {settings_file} and set:", ""]
        for finding in todo:
            setting = finding["setting"]
            lines += [f'  "{setting["key"]}": {setting["example"]}',
                      f'      {setting["why"]}',
                      f'      {setting["where"]}', ""]
        lines.append("Then run this again. A key that is present but wrong looks "
                     "exactly like")
        lines.append("one that is right until something is actually fetched.")

    blocked = [f for f in findings if f["state"] == BROKEN and not f.get("setting")]
    if blocked:
        lines += ["", "Cannot run here", "-" * 60]
        for finding in blocked:
            lines.append(f"  {finding['domain']}: {finding['detail']}")

    if not todo and not blocked:
        lines += ["", "Nothing left to configure. Start with stage 1 in "
                  "references/intake.md."]
    return "\n".join(lines)
