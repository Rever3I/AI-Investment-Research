#!/usr/bin/env python
"""三个 checker + verify() 裁决入口。

分级策略(Barry 2026-07-31 定):
    staleness   → 硬停 (raise FactCheckError)
    freq_align  → 警告
    magnitude   → 警告

"验证是硬约束" —— 警告会被忽略,硬停不会。所以陈旧数据这条必须能中断流程。

Usage:
    from scripts.factcheck import Fact, verify
    report = verify([f1, f2])          # 陈旧就 raise
    report = verify(facts, raise_on_error=False)   # 只裁决不中断
"""

from collections import defaultdict
from datetime import datetime
from statistics import median

from .fact import (
    JUMP_MIN_HISTORY,
    JUMP_RATIO_THRESHOLD,
    MAGNITUDE_RANGES,
    STALENESS_LIMITS,
    Fact,
    now_utc,
)


class FactCheckError(Exception):
    """硬停:有 Fact 没通过 error 级核查。"""

    def __init__(self, errors):
        self.errors = errors
        lines = "\n".join(f"  - [{e['check']}] {e['fact']}: {e['message']}" for e in errors)
        super().__init__(f"数值核查未通过 ({len(errors)} 项硬停):\n{lines}")


def _issue(level, check, fact, message, **extra):
    d = {
        "level": level,
        "check": check,
        "fact": fact.name,
        "entity": fact.entity,
        "value": fact.value,
        "message": message,
    }
    d.update(extra)
    return d


# ══════════════════════════════════════════════════════════════════
#  check 1: staleness —— 硬停
# ══════════════════════════════════════════════════════════════════

def check_staleness(facts, ref: datetime = None):
    """每个数字的 as_of 不得超过它 freq 允许的陈旧上限。

    防的是「抄旧数」:$NOW 写成 +14% 实际 -3.39%,就是把几天前的数字
    当成当日的用。
    """
    ref = ref or now_utc()
    issues = []
    for f in facts:
        limit = STALENESS_LIMITS.get(f.freq)
        if limit is None:
            continue
        age = f.age_seconds(ref)
        if age < 0:
            # as_of 在未来 —— 多半是时区写错,同样不该放行
            issues.append(_issue(
                "error", "staleness", f,
                f"as_of 在未来 {abs(age)/3600:.1f} 小时 (as_of={f.as_of}) —— 检查时区",
                age_seconds=age, limit_seconds=limit,
            ))
            continue
        if age > limit:
            issues.append(_issue(
                "error", "staleness", f,
                f"数据已陈旧 {_human(age)} (freq={f.freq} 上限 {_human(limit)}, "
                f"as_of={f.as_of}, 源={f.source})",
                age_seconds=round(age), limit_seconds=limit,
            ))
    return issues


def _human(seconds: float) -> str:
    seconds = float(seconds)
    if seconds < 3600:
        return f"{seconds/60:.0f} 分钟"
    if seconds < 86400:
        return f"{seconds/3600:.1f} 小时"
    return f"{seconds/86400:.1f} 天"


# ══════════════════════════════════════════════════════════════════
#  check 2: freq_align —— 警告
# ══════════════════════════════════════════════════════════════════

def check_freq_align(facts):
    """同一 group 内的 Fact 必须同频。

    防的是 DCF/估值里最常见的错:分子用季度、分母用 TTM。
    没填 group 的 Fact 不参与 —— 由调用方声明意图,不猜。
    """
    groups = defaultdict(list)
    for f in facts:
        if f.group:
            groups[f.group].append(f)

    issues = []
    for gname, members in groups.items():
        freqs = {f.freq for f in members}
        if len(freqs) <= 1:
            continue
        # 少数派更可能是写错的那个
        counts = defaultdict(list)
        for f in members:
            counts[f.freq].append(f)
        majority = max(counts, key=lambda k: len(counts[k]))
        for freq, offenders in counts.items():
            if freq == majority:
                continue
            for f in offenders:
                issues.append(_issue(
                    "warning", "freq_align", f,
                    f"group '{gname}' 内混频:本项 freq={freq},"
                    f"同组多数是 {majority} —— 同一公式不得跨频计算",
                    group=gname, group_freqs=sorted(freqs),
                ))
    return issues


# ══════════════════════════════════════════════════════════════════
#  check 3: magnitude —— 警告
# ══════════════════════════════════════════════════════════════════

def check_magnitude(facts, history_fn=None):
    """两道:(a) 按 unit 的绝对区间;(b) 与历史同名 Fact 的跳变比。

    history_fn(name, entity) -> [float, ...]  历史值,由 store 提供。
    传 None 就只做 (a)。跳变基线用中位数,抗单点异常。
    """
    issues = []
    for f in facts:
        lo, hi = MAGNITUDE_RANGES.get(f.unit, (None, None))
        av = abs(f.value)
        if hi is not None and av > hi:
            issues.append(_issue(
                "warning", "magnitude", f,
                f"绝对值 {av:g} 超出 unit={f.unit} 的合理上界 {hi:g} —— 多半是单位错或取错字段",
                bound="upper", limit=hi,
            ))
        elif lo is not None and av != 0 and av < lo:
            issues.append(_issue(
                "warning", "magnitude", f,
                f"绝对值 {av:g} 低于 unit={f.unit} 的合理下界 {lo:g} —— 检查是否单位缩放错",
                bound="lower", limit=lo,
            ))

        if history_fn is None:
            continue
        try:
            hist = [abs(v) for v in (history_fn(f.name, f.entity) or []) if v is not None]
        except Exception:
            hist = []
        hist = [v for v in hist if v > 0]
        if len(hist) < JUMP_MIN_HISTORY:
            continue
        base = median(hist)
        if base <= 0:
            continue
        if av > base * JUMP_RATIO_THRESHOLD:
            issues.append(_issue(
                "warning", "magnitude", f,
                f"较历史中位数跳变 {av/base:.1f}x (历史中位 {base:g},n={len(hist)}) "
                f"—— 超过 {JUMP_RATIO_THRESHOLD:g}x 阈值",
                jump_ratio=round(av / base, 2), history_median=base, history_n=len(hist),
            ))
    return issues


# ══════════════════════════════════════════════════════════════════
#  verify —— 裁决入口
# ══════════════════════════════════════════════════════════════════

def verify(facts, raise_on_error=True, record=True, ref=None):
    """跑全部核查,返回裁决 report。

    facts        Fact 列表(或 dict 列表,自动转)
    raise_on_error  True 时,有 error 级问题就 raise FactCheckError
    record       True 时把通过的 Fact 落 fact_log(magnitude 的历史基线靠它长)
    ref          比较基准时间,测试用

    返回 {"ok", "errors", "warnings", "checked", "facts"}
    """
    facts = [f if isinstance(f, Fact) else Fact.from_dict(f) for f in facts]

    # store 只是可选依赖:拿不到就退化成「只做绝对区间,不做跳变检测」,
    # 绝不因为落库层出问题而让核查本身跑不起来。
    try:
        from . import store as _store
        store = _store
        history_fn = _store.history
    except Exception:
        store = None
        history_fn = None

    issues = []
    issues += check_staleness(facts, ref=ref)
    issues += check_freq_align(facts)
    issues += check_magnitude(facts, history_fn=history_fn)

    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]

    # 只落通过硬停的 Fact —— 陈旧数据不该污染 magnitude 的历史基线
    if record and store is not None:
        bad = {i["fact"] for i in errors}
        try:
            store.record_many([f for f in facts if f.name not in bad])
        except Exception:
            pass  # 落库永不阻塞裁决

    report = {
        "ok": not errors,
        "checked": len(facts),
        "errors": errors,
        "warnings": warnings,
        "facts": [f.to_dict() for f in facts],
    }
    if errors and raise_on_error:
        raise FactCheckError(errors)
    return report


def format_report(report) -> str:
    """人读的裁决输出。"""
    lines = []
    n, ne, nw = report["checked"], len(report["errors"]), len(report["warnings"])
    head = "✅ 全部通过" if report["ok"] and not nw else ("⛔ 有硬停" if ne else "⚠️ 有警告")
    lines.append(f"{head} — 核查 {n} 项,硬停 {ne},警告 {nw}")
    for i in report["errors"]:
        lines.append(f"  ⛔ [{i['check']}] {i['fact']} = {i['value']}: {i['message']}")
    for i in report["warnings"]:
        lines.append(f"  ⚠️ [{i['check']}] {i['fact']} = {i['value']}: {i['message']}")
    return "\n".join(lines)
