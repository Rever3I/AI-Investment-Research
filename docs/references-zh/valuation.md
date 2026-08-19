# 阶段 3 —— 估值，以及可选的分歧压力测试

拿一条 `Thesis` 产出一条 `Valuation`：带概率的情景估值，外加一个交互式页面，让读者
可以去推假设，而不是接受一个数字。

## 算术不归你做

每个数字都来自 `airesearch/valuation/`，它用 `Decimal` 计算，并拒绝会产生无意义结果
的输入。不要心算，也不要拿它的答案和你自己的估计去核对——如果两者不一致，是模块对，
因为一年之后还对的是它。

```python
from airesearch.valuation import (
    discounted_cash_flow, implied_growth_rate, scenario_values, expected_value,
)
```

这里刻意**没有默认折现率**。你要说出它是多少，并说出它从哪来，因为这份来源会存进
记录，也正是它让这次估值日后可复核。美国十年期国债收益率加一个股权风险溢价是常见的
构造方式；它并不适用于每一个标的，而一个内置默认值，就是一套美股形状的假设被悄悄
套到另一个地方的公司头上的方式。

## 取到 thesis

```python
from airesearch.data.thesis_store import get_thesis

thesis = get_thesis(thesis_id)
```

还没有研究过任何东西时会抛 `FileNotFoundError`。接住它，告诉用户先跑一次阶段 2，
不要把 traceback 甩出去。背后没有 thesis 的估值，是一个没有论证支撑的目标价，所以
`save_valuation` 会拒绝它。

## 输入

起点是股东盈余：净利润，加折旧摊销，减资本开支。它必须为正——股东盈余 DCF 不适用于
一门不产生股东盈余的生意，模块会拒绝，而不是把算术本来会给你的那个负目标价交出来。
对亏损公司，说清这个方法不适用，然后停下。里面每一个数字都要先过 Fact 契约，并且
分好组，这样季度数字不会被 TTM 数字除：

SEC 适配器返回的就是下面这四项 Fact，已经分好组：

```python
from airesearch.data.adapters import configure, fetch
from airesearch.factcontract import verify

configure()
facts = fetch("us_equity", ticker)      # net income, D&A, capex, share count
price = fetch("price", ticker)[0]       # the reverse DCF is a ratio against it
verify(facts + [price])                 # hard-stops on anything stale
```

如果是用别的方式取到的，同样这几个数字要手工声明：

```python
from airesearch.factcontract import Fact, verify

verify([
    Fact(name="NVDA_net_income", value=..., unit="usd", freq="ttm",
         as_of=filing_date_iso, source="sec-xbrl", entity="NVDA", group="oe"),
    Fact(name="NVDA_dep_amort", value=..., unit="usd", freq="ttm",
         as_of=filing_date_iso, source="sec-xbrl", entity="NVDA", group="oe"),
    Fact(name="NVDA_capex", value=..., unit="usd", freq="ttm",
         as_of=filing_date_iso, source="sec-xbrl", entity="NVDA", group="oe"),
])
```

## 情景

三档通常是对的：bull、base、bear。关键在于**概率是你给的、并且明说出来**，因为
阶段 4 会直接拿它们当仓位计算的输入。没认真想过的概率，会产出一个看起来很量化、
实际不是的仓位。

```python
base_inputs = dict(
    owner_earnings=owner_earnings,
    growth_rate="0.10",
    discount_rate="0.10",          # no default; yours, with a source
    terminal_growth="0.03",
    years=10,
    shares_outstanding=shares,
)
scenarios = scenario_values([
    {"name": "bull", "probability": 0.25, "growth_rate": "0.20",
     "assumptions": "networking attach rate holds above 30%"},
    {"name": "base", "probability": 0.50, "growth_rate": "0.10"},
    {"name": "bear", "probability": 0.25, "growth_rate": "0.00",
     "assumptions": "hyperscaler capex digests for two years"},
], base_inputs)
```

每个情景只覆盖它点名的那几项，其余全部来自 `base_inputs`。`assumptions` 那句话要写到
读者能看出这一档特殊在哪——「增长更高」不是一个假设，那只是把增长率重说了一遍。

概率必须加总为 1。记录本身会强制这一点，因为一组加不到 1 的概率会污染下游的仓位计算。

## 反向 DCF 才是更有用的产出

```python
from airesearch.valuation import PriceOutsideBracket

implied = None
try:
    implied = implied_growth_rate(
        market_value=current_price, owner_earnings=owner_earnings,
        discount_rate="0.10", terminal_growth="0.03", years=10,
        shares_outstanding=shares,
    )
except PriceOutsideBracket as exc:
    out_of_range = exc          # exc.direction is "below" or "above"
```

它把「这只票便宜吗」换成了「价格假设了未来十年每年 18%——这会发生吗」，而后者是读者
真的能判断的问题。把它放在最前面说。

`PriceOutsideBracket` 意味着搜索区间里没有任何增长率能拟合当前价格，`exc.direction`
告诉你是哪一侧。**报它给你的方向，不要报你记得的那个**——`"below"` 表示价格低于这份
股东盈余即使萎缩时的价值；`"above"` 表示价格高于极快增长时的价值，这对一门股东盈余
因为资本开支吃掉而接近于零的生意来说很常见。这是两个相反的结论，说错一个比两个都不说
更糟。

同时报出每个情景的 `terminal_share`。一个 85% 价值来自永续段的估值，说的是折现率而不是
这门生意，读者有权知道自己看到的是哪一种。

## 交互式页面

```python
from pathlib import Path

from airesearch.config import output_language
from airesearch.valuation.report import render

page = render(
    ticker=ticker, scenarios=scenarios, owner_earnings=owner_earnings,
    discount_rate="0.10", terminal_growth="0.03", years=10,
    shares_outstanding=shares, discount_rate_source=rate_source,
    market_price=current_price, implied_growth=implied, currency="$",
    generated_at=today_iso, language=output_language(),
)
path = Path("reports") / f"{ticker}-{today_iso}.html"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(page, encoding="utf-8")   # encoding is not optional
```

这个文件完全自包含——没有 CDN、没有外部字体、没有任何网络请求——所以几年后在一台
断网的机器上还能打开。把它的路径存进记录，并告诉用户文件在哪。

## 输出语言

`output_language()`（上面已导入）决定读者看到的一切用什么语言。

**要翻译：** 你的说明文字，以及每个情景的 `assumptions` 字符串。

**永远不要翻译：** 情景的 `name` 值（`bull` / `base` / `bear`——报告按它们匹配来给行
加样式，阶段 4 也要读它们），以及 `discount_rate_source` 里点出具体工具名称的部分，
那是来源信息。

## 保存

```python
from airesearch.data.schema import Valuation
from airesearch.data.valuation_store import save_valuation

valuation = Valuation(
    thesis_id=thesis.id,
    scenarios=scenarios,
    discount_rate_source="US 10Y (4.2%) + 5% equity risk premium",
    html_artifact_path=str(path),
    valued_at=today_iso,
)
row_id = save_valuation(valuation)
```

重新估值是追加而不是覆盖：旧的数字是「当初给这个仓位定大小时相信的是什么」的记录。

---

# 分歧压力测试（可选）

估值是给 thesis 施压的自然时机：数字已经算出来了，仓位还没定。这一段默认关闭，
除非用户主动要求或在配置里打开。

```python
from airesearch.config import load_profile

if not load_profile()["debate_enabled"]:
    ...   # skip, and say so once rather than running it anyway
```

用户关掉的一层，是他已经对其成本做过判断的一层。

## 它是干什么的

不是为了得出结论。数字已经算完，下一步就是定仓位；一个把基准情形重说一遍的委员会
只增加仪式感，不增加信息。

它能产出而别的环节产不出的，是那张**分歧地图**：那些互相碰撞之后仍然存活、且仍未解决
的论点，每一条附上「什么证据能了结它」。这才是一年后值得回头读的部分，因为它提前
点出了这份 thesis 脆弱在哪。一个把三种观点平均成一个裁决的流程，恰好毁掉了唯一一件
读者自己写不出来的产出。

## 两种模式

`mode="checklist"` —— 默认。一个分析性的声音去压这几个点：

- 哪一条主张承担了最多的重量，如果它错了会怎样？
- 空头论点需要什么条件成立，你怎么能早点知道？
- thesis 里的哪一条证伪条件此刻离触发最近？
- 永续价值占比落在哪里，故事撑得起它吗？
- 一个已经持有对面仓位一年的人会说什么？

`mode="persona_debate"` —— 一组具名的投资者声音，如果用户选了这个。每个声音从一套
方法论出发争论，而不是表演一种性格：一个看质量与护城河的声音，一个看安全边际的声音，
一个问「我漏了什么」的声音，一个看宏观状态的声音。两轮就够——第一轮陈述立场，第二轮
回应针对自己最强的那个反驳。

不管哪种模式，有用的产出都一样：哪里达成一致，哪里没有，以及什么证据能推动每一个
未解决的点。

这一段里引入的任何数字，都和这里其他数字一样要过 Fact 契约。一个建立在记忆中某个
百分比之上的空头论点不是空头论点，是情绪。

## 保存结论

```python
from airesearch.data.schema import Verdict
from airesearch.data.verdict_store import save_verdict

verdict = Verdict(
    valuation_id=valuation.id,
    mode="checklist",                      # or "persona_debate"
    votes=[{"voice": "...", "call": "...", "why": "..."}],
    dissent_map="What was not resolved, and what would settle each point.",
    authored_at=today_iso,
)
row_id = save_verdict(verdict)
```

checklist 模式下 `votes` 可以为空。`dissent_map` 不该为空——「没有未解决的分歧」本身
就是一个值得写出来的发现，而一个空字符串读起来像是漏了，而不是一个结论。

不要翻译 `mode`：记录会拿它和 `"checklist"`、`"persona_debate"` 做严格校验。

---

## 收尾

先说隐含增长率，然后是概率加权价值对比当前价格，然后是带永续占比的情景表。说清页面
在哪。如果跑了分歧压力测试，那一节要以**没有被解决的东西**开头，而不是以裁决开头。

到此为止——定仓位是阶段 4，不会没被要求就跑。

不要告诉用户买入或卖出。呈现价格假设了什么、你相信什么；决定是他的。
