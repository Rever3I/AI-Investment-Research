#!/usr/bin/env python
"""Fact — 数值裁决层的输入契约。

任何要进报告/帖子/模型的数字,必须先声明成一条 Fact 才有资格被验证。
裸 float 进不来 —— 这本身就是第一道闸。

Design principles (与 pipeline_db.py 一致):
  - 纯 stdlib,无外部依赖
  - 所有时间戳 ISO 8601 UTC
  - 构造即校验:字段缺失/取值非法在构造时就炸,不留到下游

Usage:
    from scripts.factcheck import Fact, verify
    f = Fact(name="NVDA_chg_pct", value=-3.39, unit="pct",
             freq="daily", as_of="2026-07-31T20:15:00Z", source="yfinance",
             entity="NVDA")
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

# ── 取值域 ────────────────────────────────────────────────────────
UNITS = ("pct", "usd", "shares", "ratio", "x", "count", "bps")
FREQS = ("intraday", "daily", "weekly", "monthly", "quarterly", "ttm", "annual", "point")

# ── staleness 阈值表:每种 freq 允许的最大陈旧秒数 ──────────────────
# daily 给 4 天是为了容忍周末 + 假日(周五收盘的数据周二早上仍然是"最新")。
# point = 静态值(如行权价、股本结构),无自然陈旧概念。
_DAY = 86400
STALENESS_LIMITS = {
    "intraday": 60 * 60,        # 报价:1 小时(yfinance ~15min 延迟 + 余量)
    "daily": 4 * _DAY,          # 日线/当日涨跌
    "weekly": 10 * _DAY,
    "monthly": 45 * _DAY,
    "quarterly": 100 * _DAY,    # 季报
    "ttm": 100 * _DAY,          # TTM 随季报滚动
    "annual": 400 * _DAY,
    "point": None,              # 不校验
}

# ── magnitude 合理区间:按 unit 给绝对值上下界 ──────────────────────
# 命中只是警告 —— 越界的数字未必错,但绝大多数情况是单位错或取错字段。
MAGNITUDE_RANGES = {
    "pct":    (0.0, 500.0),        # 单日涨跌 500% 以上基本是复权/单位问题
    "usd":    (1e-4, 1e13),        # 10 万亿美元以上、万分之一美元以下
    "shares": (1.0, 1e11),
    "ratio":  (0.0, 1000.0),
    "x":      (0.0, 1000.0),       # 倍数(P/E 等);负值单独处理
    "count":  (0.0, 1e12),
    "bps":    (0.0, 100000.0),
}

# magnitude 跳变检测:与历史同名 Fact 的中位数相比,超过这个倍数就警告
JUMP_RATIO_THRESHOLD = 10.0
# 历史样本少于这个数就不做跳变判断(样本太少,基线不可信)
JUMP_MIN_HISTORY = 3


class FactError(ValueError):
    """Fact 构造非法。"""


def parse_ts(ts: str) -> datetime:
    """解析 ISO 8601 时间戳,统一成 aware UTC。接受结尾 'Z'。"""
    if isinstance(ts, datetime):
        dt = ts
    else:
        s = str(ts).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise FactError(f"as_of 不是合法 ISO 8601 时间戳: {ts!r}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Fact:
    """一个待验证的数字。

    name     取值的稳定标识(跨次运行必须一致,magnitude 跳变检测靠它对齐历史)
    value    数值本身
    unit     UNITS 之一
    freq     FREQS 之一 —— 决定 staleness 阈值,也是 freq_align 的比较依据
    as_of    这个数字代表的时点(不是抓取时点)
    source   来源标识,如 "yfinance" / "sec-xbrl" / "cboe"
    entity   主体,如 ticker;宏观指标可填指标名
    currency 币种,本期只记录不校验(留痕,以后开闸不用改结构)
    group    参与同一公式的 Fact 填同一个 group,freq_align 只在组内比较
    note     自由备注,原样落库
    """

    name: str
    value: float
    unit: str
    freq: str
    as_of: str
    source: str
    entity: str = ""
    currency: str = ""
    group: str = ""
    note: str = ""
    _as_of_dt: datetime = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if not self.name or not str(self.name).strip():
            raise FactError("name 不能为空")
        if self.value is None:
            raise FactError(f"{self.name}: value 不能为 None")
        try:
            self.value = float(self.value)
        except (TypeError, ValueError) as e:
            raise FactError(f"{self.name}: value 不是数字 ({self.value!r})") from e
        if self.value != self.value:  # NaN
            raise FactError(f"{self.name}: value 是 NaN")
        if self.unit not in UNITS:
            raise FactError(f"{self.name}: unit={self.unit!r} 不在 {UNITS}")
        if self.freq not in FREQS:
            raise FactError(f"{self.name}: freq={self.freq!r} 不在 {FREQS}")
        if not self.source or not str(self.source).strip():
            raise FactError(f"{self.name}: source 不能为空 —— 每个数字必须有出处")
        self._as_of_dt = parse_ts(self.as_of)
        # 归一化成标准 ISO,保证落库格式一致
        self.as_of = self._as_of_dt.isoformat()

    @property
    def as_of_dt(self) -> datetime:
        return self._as_of_dt

    def age_seconds(self, ref: datetime = None) -> float:
        return ((ref or now_utc()) - self._as_of_dt).total_seconds()

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_as_of_dt", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Fact":
        allowed = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "_as_of_dt"}
        missing = [k for k in ("name", "value", "unit", "freq", "as_of", "source") if k not in allowed]
        if missing:
            raise FactError(f"Fact 缺字段: {', '.join(missing)}")
        return cls(**allowed)
