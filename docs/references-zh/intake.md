# 阶段 1 —— 发现：找候选标的

流水线的入口。不管一只票是从哪条路进来的，离开这一段时它都是一条 `Candidate` 记录，
所以后面每一段判断筛子来的想法和判断来的想法，用的是同一把尺子。

## 默认行为：通用开放搜索

没有内置的筛选清单，没有红线，没有质量记分卡。除非用户保存过自己的条件 profile，
否则就按他实际问的东西做一次开放的探索性搜索。

这是刻意的设计。套用一个用户从没配置过的过滤器，等于用他看不见的理由悄悄丢掉标的。
如果你发现自己正要按一条没人设过的规则否掉一个候选，停下来——把这个观察摆给用户，
让他决定要不要把它变成一条保存下来的标准。

## 两条入口

**筛子优先（Screen-first）** —— 用户想从一个池子里捞候选（「帮我在工业股里找几个便宜
又有质量的」）。先看有没有存好的条件 profile：有就套用它，并如实记进候选记录；没有就
跑通用搜索，把 `screened` 设成 `False`、`profile_used` 留空。

不要为了让记录看起来完整而编一个 profile 名字。`screened=False` 是一条诚实的记录，
一个指向不存在 profile 的名字不是。

**判断优先（Thesis-first）** —— 用户先给出一个观点（「电网并网排队才是 AI 资本开支
的真正天花板」），想要能表达这个观点的标的。从这个判断往外推到具体的 ticker，用
WebSearch 去找谁真的站在那条价值链上。这条路没有固定的条件清单，也不该有：判断本身
就是过滤器。

## 保存下来的筛选条件

```python
from airesearch.data.schema import ScreenProfile
from airesearch.data.screen_store import (
    save_screen_profile, get_screen_profile, list_screen_profiles,
    delete_screen_profile,
)

profile = get_screen_profile("quality-industrials")   # None if there is no such name
available = list_screen_profiles()                    # alphabetical; [] before any exist
```

`list_screen_profiles` 在一次都没保存过时会抛 `FileNotFoundError`——全新安装根本没有
这张表。接住它，当作「没有任何 profile」处理，不要把 traceback 甩出去。

用户说「记住这套条件」时保存：

```python
save_screen_profile(ScreenProfile(
    name="quality-industrials",
    criteria={"market": "US", "sector": "industrials",
              "min_roic": 0.12, "max_net_debt_ebitda": 2.5},
    notes="工业股，只看资本回报率和杠杆，不看估值",
))
```

`criteria` 的键完全由用户定，这里不解释它们，也不拿它们去对任何「允许的指标」清单。
一套固定词汇表，就是这条流水线承诺不强加的那份内置筛选清单。所以你要做的是把用户
说的条件如实记下来，而不是翻译成某种规范格式。

同名保存会覆盖。筛子是会被修订的东西——一条规则收紧、一个阈值挪动——自动留版本只会
让 `profile_used="quality-industrials"` 指向好几套不同的条件，而没人分得清跑的是哪一套。

套用一个 profile 之后，候选记录要如实反映这件事：

```python
candidate = Candidate(
    ..., entry_path="screen",
    source_note=profile.name,
    screened=True, profile_used=profile.name,
)
```

`screened=True` 的意思是**一套写下来的条件真的被套用了**。跑的是通用搜索却写 `True`，
会让「这只票是怎么进来的」这个问题在几个月后无法回答，而那正是这个字段存在的唯一理由。

删掉一个 profile 不会改动已有的候选记录：哪套条件产出了哪只票是历史事实，因为 profile
后来被删了就去改它，等于修改过去。

## 产出 Candidate 记录

每只票建一条 `Candidate` 并存下来。`airesearch/data/schema.py` 里的 dataclass 就是
契约——它在构造时就校验，所以格式不对的记录在这里就失败，而不是漏到三层之后。

```python
from airesearch.data.schema import Candidate
from airesearch.data.candidate_store import save_candidate

candidate = Candidate(
    ticker="NVDA",
    entry_path="screen",              # "screen" or "thesis"
    source_note="general search",     # or the thesis text, verbatim, if thesis-first
    market="US",                      # any market string the user's adapters support
    raw_rationale="One sentence on why this name surfaced.",
    discovered_at="2026-08-04T12:00:00Z",
)
row_id = save_candidate(candidate)    # also stamps candidate.id
```

三个字段比看上去重要：

- `screened=False` 配一个空的 `profile_used`，对通用搜索来说是一条完整、正常的记录。
  它不是没写完——不要为了填空自己编一个 profile 名字。反过来，套用了 profile 就要把
  两个字段都填上，否则这次筛选等于没发生过。
- 判断优先那条路上，`source_note` 存的是用户的原话，逐字。后面几段要拿它做对比，
  改写一遍就把要被检验的东西弄丢了。
- `id` 在保存前是 `None`。`save_candidate` 之后它带上行号，阶段 2 要靠它把工作挂到
  这个候选上。

## 数字

任何会到达用户面前的数字，都要先过 `airesearch/factcontract/` 的 Fact 契约。它对陈旧
数据直接中断，对不合理的单位或量级给警告。

```python
from airesearch.factcontract import Fact, verify

verify([Fact(name="NVDA_chg_pct", value=-3.39, unit="pct", freq="daily",
             as_of="2026-08-04T20:15:00Z", source="sec-xbrl", entity="NVDA")])
```

不要凭记忆、也不要从来路不明的文章里报出价格、百分比或倍数。取到它、声明它、验证它。

## 输出

用用户配置的语言写：

```python
from airesearch.config import output_language

lang = output_language()   # "en" by default; "zh-CN", "ja", anything the model reads
```

但要清楚这条规则覆盖哪些内容。后面几段会在其中一些字段上做选择和比对，那里放一个被
翻译过的值不会当场报错——它会在几个月后、当什么都匹配不上的时候才失败。

**要翻译：** 你在对话里的说明和总结，以及 `raw_rationale`。

**永远不要翻译：**

| 字段 | 为什么 |
| --- | --- |
| `ticker` | 它是标识符，不是正文 |
| `market` | 适配器按它取值。`"US"` 就得是 `"US"`，绝不能写成 `"美股"`——这个字段没有任何校验，所以一个翻译过的值会干干净净地存下来，然后匹配不上任何适配器 |
| `entry_path` | 固定值：`"screen"` 或 `"thesis"`，任何语言下都一样 |
| `profile_used` | 它是一个文件名 |
| `source_note` | 判断优先那条路上这是用户自己的话。阶段 5 之后要拿它做 diff，而翻译就是改写——改写会毁掉要被检验的那个东西。无论 `output_language` 是什么，他用什么语言写的就保持什么语言 |

把候选连同各自那一句理由一起呈现出来，并说清是哪条入口产生的——筛子优先的话，
点出用的是哪个 profile，或者直接说没有配置 profile、这是一次通用搜索。

到此为止。深度研究是阶段 2，由用户决定什么时候开始；没被要求就跑，是把他的时间和
token 花在他可能并不想要的标的上。
