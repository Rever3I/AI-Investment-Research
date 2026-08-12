# 阶段 4 —— 定仓位

把阶段 3 的情景概率转换成占总资金的一个比例。算术在
`airesearch/valuation/sizing.py` 里，不归你复现。

## 先把话说在前面

Kelly 是把精确的算术用在不精确的输入上。它最大化的是长期增长率——**给定那些概率**，
而那些概率是几层之前一个人的判断。用没人认真想过的数字算出来的 Kelly 比例，是一个
看起来很量化、实际不是的仓位。

所以在定仓位之前，先看一眼那些概率，问它们是推出来的还是随手凑的。如果是随手凑的，
就把这件事说出来——这比在它们之上算到小数点后两位的权重有用得多。

## 计算

```python
from airesearch.config import load_profile
from airesearch.data.valuation_store import get_valuation
from airesearch.valuation.sizing import size_position

valuation = get_valuation(valuation_id)
profile = load_profile()

result = size_position(
    valuation.scenarios,
    market_price=current_price,          # verified, not remembered
    method=profile["sizing_method"],     # half_kelly by default
    weight=profile["fixed_pct"],         # only used by fixed_pct and custom
    cap=profile["position_cap"],         # concentration limit; 1.0 is none
)
```

全新安装时 `get_valuation` 会抛 `FileNotFoundError`；接住它，说先跑一次阶段 3。

市场价格在到这里之前要先过 Fact 契约——整个计算就是一个对它的比值，所以一个陈旧的
价格会悄悄把答案整体缩放。行情适配器不需要任何配置：

```python
from airesearch.data.adapters import configure, fetch
from airesearch.factcontract import verify

configure()
quote = fetch("price", ticker)[0]
verify([quote])                 # intraday facts go stale in an hour
current_price = quote.value
```

四种方法，都在 profile 里：

- `half_kelly`（默认）—— 对「概率可能是错的」这件事的常规对冲。全 Kelly 只有在概率
  完全正确时才是增长最优的，而一旦不正确，它的回撤很凶。
- `full_kelly` —— 可以选，结果里会说明代价。
- `fixed_pct` —— 不看边际，直接用 profile 里的 `fixed_pct` 权重。
- `custom` —— 用户自己定了仓位，把他的数字作为 `weight=` 传进去。

后两种仍然会报出 Kelly 本来会给的答案，供对照。

这里每一个比例都是分数，不是百分数：`0.05` 就是总资金的百分之五。传 `5` 想表示百分之
五会被拒绝，而不是悄悄把仓位放大一百倍。

## 会让人意外的几个答案

**零是一个真答案。** 当期望收益在当前价格下不为正，Kelly 给出的仓位就是零。那是算术
在拒绝下注，不是缺一个数字，把它报成「暂无建议」是曲解。直接说这个价格上没有边际。

**被上限截断的仓位和没被截断的不是一回事。** 如果集中度上限约束了答案，`result.capped`
为真，说明里也会写。把这件事传出去——「Kelly 想要 30%，你的上限说 5%」和「Kelly 就
想要 5%」，对做决定的人来说完全不同。

**最优解超过 100% 时报的是 100%，不是杠杆。** 这个模块不计算带杠杆的仓位；如果边际
真有那么大，约束就不在算术这一侧了。发生这种情况时 `result.clipped` 为真，说明里会
写——一定要传出去，否则 `full_kelly` 读起来像是最优解，而它其实是天花板，而天花板的
一半不是半 Kelly。

**远高于当前价格的目标价会被当作单位错误拒绝。** 常见原因是把整体股权价值填在了每股
数字的位置上，否则它会按一个虚构的 200 倍回报把仓位顶到最大。

**隐含全损的情景会被拒绝。** 对一个会把仓位打光的结果，Kelly 是没有定义的，而那种
情况需要的是「还要不要持有这个标的」的决定，不是一个权重。

## 保存

```python
from airesearch.data.schema import Portfolio
from airesearch.data.portfolio_store import save_portfolio

portfolio = Portfolio(
    valuation_id=valuation.id,
    sizing_method=result.method,
    recommended_position_pct=float(result.percent),
    kelly_inputs={
        "full_kelly": float(result.full_kelly),
        "clipped": result.clipped,      # full_kelly is a ceiling, not the optimum
        "capped": result.capped,        # the concentration limit bound the answer
        "expected_return": float(result.expected_return),
        "market_price": float(current_price),
        "outcomes": [
            {"name": o["name"], "probability": float(o["probability"]),
             "return": float(o["return"])}
            for o in result.outcomes
        ],
    },
    sized_at=today_iso,
)
row_id = save_portfolio(portfolio)
```

把输入也存下来，不要只存答案。一个背后看不见概率的权重，日后没法被质疑——包括被
产出它的那个人质疑。

注意 `recommended_position_pct` 是百分数（4.25 表示总资金的 4.25%），而
`result.fraction` 是分数。`result.percent` 负责这个转换。

## 输出语言

说明文字跟随 `output_language()`。不要翻译 `sizing_method`——记录会拿它和 `half_kelly`、
`full_kelly`、`fixed_pct`、`custom` 做校验——也不要翻译 `kelly_inputs` 里的情景名称。

## 收尾

报出权重、用的方法、它来自的期望收益，以及是否被上限约束过。把答案所依赖的那些概率
一并列出来，因为如果用户不同意，他该推的正是这些。

不要告诉用户去下单。这是从既定假设推出来的一个权重；要不要照做是他的事。
