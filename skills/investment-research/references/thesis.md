# 阶段 2 —— 研究：写成可被证伪的观点

把阶段 1 产出的 `Candidate` 变成一条 `Thesis`：流水线上第一个把观点落成文字、并且
让它可以被证伪的地方。

## 它和一份公司简介的区别

复述一遍 10-K 谁都会。真正的工作在两个小节里，缺了它们的 thesis 只是一份披着 thesis
外衣的简报：

**变异认知（Variant perception）** —— 你相信而市场不相信的是什么，以及这个差为什么
存在。「英伟达卖了很多 GPU」是共识，一文不值。「市场给 GPU 定了价，却忽略了网络业务
现在占系统收入三分之一、附着率高于卖方模型的假设」才是观点。如果你说不清价格已经
反映了什么，那你还没有 thesis；直说这一点，别把共识包装一遍。

**证伪条件（Falsifiers）** —— 具体的、可观察的、会让你被证明是错的那些事。要写成
未来的读者不用重新推一遍全部论证就能拿去和现实对照：「超大规模厂商资本开支连续两个
季度指引下调」，而不是「如果 AI 周期转向」。阶段 5 之后要读这些条件，拿它们和实际
发生的事做 diff，而这只有在它们指向事件而不是情绪时才成立。

## 取到候选

```python
from airesearch.data.candidate_store import get_candidate, list_candidates

candidate = get_candidate(candidate_id)          # if the user named an id
recent = list_candidates(market="US", limit=10)  # to pick from
```

从来没保存过任何东西时，两者都会抛 `FileNotFoundError`——全新安装根本没有 candidates
这张表。接住它，告诉用户先跑一次阶段 1，不要把 traceback 直接甩出去。

如果用户给了一个背后没有候选记录的 ticker，同理：没有真实的 `candidate_id` 就存不了
thesis。`save_thesis` 会抛 `ValueError` 并点出那个 id，数据库的外键也会拒绝它——
这样阶段 5 永远不会解析到一个指向不存在候选的 thesis。

## 这份文档

按对这家公司最顺的顺序覆盖这几块：

- **生意概览** —— 卖什么、卖给谁、怎么赚钱。单位经济能算清的地方就算清。
- **管理层** —— 谁在管，他们的记录、激励、持股。资本配置的历史通常比履历更能说明问题。
- **竞争格局** —— 市场里还有谁，结构是什么，定价权在哪一端。要点出替代品，不能只
  列同业名单。
- **市场空间（TAM）** —— 机会有多大，更有用的是这个规模依赖哪些假设。一个没人能
  证伪的 TAM 只是装饰。
- **风险** —— 8 到 12 条，且是这门生意特有的。「宏观环境可能恶化」适用于历史上每一
  只股票，因此哪一只都不该写它。
- **变异认知** 和 **证伪条件**，如上。

## 取数字

适配器返回的是 `Fact` 对象，所以一个数字到手时就已经带着来源、单位和数据时点。
配置一次，然后取：

```python
from airesearch.data.adapters import configure, fetch, status_report

print(status_report(configure()))          # what can run in this installation
facts = fetch("us_equity", ticker)         # net income, D&A, capex, share count
price = fetch("price", ticker)[0]          # works with no configuration
```

如果某个 domain 报告自己不可用，说清缺的是哪一项设置，不要绕过去——`status_report()`
会打印出确切的配置键和去哪儿拿。用别的方式弄来的数字没有来源，而防住这一点正是这一
段存在的意义。

中国上市公司需要已授权的 Wind 终端，而那个适配器没有在真实终端上验证过。如果
`cn_equity` 不可用，直说，不要拿一个美股数据源顶上。

## 数字契约

每个数字在进入正文之前都要过 Fact 契约：

```python
from airesearch.factcontract import Fact, verify

verify([
    # as_of is the period the figure describes. Use the real filing date — the
    # ttm limit is 100 days, so a stale one hard-stops here rather than in print.
    Fact(name="NVDA_revenue_ttm", value=130_500_000_000, unit="usd", freq="ttm",
         as_of=filing_date_iso, source="sec-xbrl", entity="NVDA",
         group="valuation"),
])
```

它对陈旧数据直接中断，对单位或量级看起来不对的给警告。喂给同一个计算的 Fact 要共用
同一个 `group`，这正是拦住「季度分子除以 TTM 分母」的机制。

不要凭记忆、也不要从来路不明的文章里报出价格、倍数或增长率。取到它、声明它、验证它。
每一条实质性主张的出处记进 `data_sources`——一年后数字全变了的时候，正是这份清单让
这篇 thesis 还能被审计。

## 输出语言

```python
from airesearch.config import output_language
lang = output_language()   # "en" by default; "zh-CN", "ja", anything the model reads
```

正文用那个语言。有些值不能跟着走，因为后面几段要在它们上面做选择和比对——那里放一个
被翻译过的值不会当场报错，它会在几个月后、当什么都匹配不上的时候才失败。

**要翻译：** `business_overview`、`management`、`competitors`、`tam`、`risks` 里的
每一条、`variant_perception`、`falsifiers` 里的每一条，以及你在对话里的说明。

**永远不要翻译：** `data_sources` 里的条目（它们是来源字符串，例如
`sec-xbrl:10-K FY2025`，会被字面匹配），以及来源候选的 `source_note`——判断优先那条
路上那是用户自己的话，阶段 5 要拿它做 diff。翻译就是改写，而改写会毁掉要被检验的那个
东西。

## 保存

```python
from airesearch.data.schema import Thesis
from airesearch.data.thesis_store import save_thesis

thesis = Thesis(
    candidate_id=candidate.id,
    business_overview="...",
    management="...",
    competitors="...",
    tam="...",
    risks=["...", "..."],              # at least one; aim for 8-12
    variant_perception="...",
    falsifiers=["...", "..."],
    data_sources=["sec-xbrl:10-K FY2025", "Q1 FY2026 call transcript"],
    authored_at="2026-08-04T12:00:00Z",
)
row_id = save_thesis(thesis)           # also stamps thesis.id
```

重新研究一只票是写一条新的 thesis，而不是覆盖旧的。这是刻意的：那份历史正是阶段 5
用来对账的东西。

## 收尾

报出这份 thesis 和它的行号。到此为止——估值是阶段 3，由用户决定什么时候开始。没被
要求就跑，是把他的时间花在一个他可能还不想要的数字上，而一份 thesis 本身就值得单独
读一遍。
