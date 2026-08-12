# 一人投资交易投研团队 Pro 版

[English](README.en.md) · 简体中文

按对冲基金的投研流程搭建，从选股到建仓五段闭环，财报直连 SEC 官方数据，拒绝幻觉，不预测涨跌，只分析股票价值。

作为单个 SKILL.md 包交付，不绑定 Claude Code，也不是托管服务。装进任何支持 SKILL.md 的 AI 工具，配置你自己的市场和数据源，自己跑。

## 详细功能

一个 skill，五个阶段。每一段交给下一段的是一份经过校验的结构化记录而不是一段文字，所以从量化筛子来的标的和从宏观判断反推来的标的，用的是同一把尺子。

| 阶段 | 做什么 | 产出 |
| --- | --- | --- |
| 发现 | 自定义条件筛选，也支持从一个观点反推能够表达的股票 | `Candidate` |
| 研究 | 对股票生成完整研究报告，AI 对话辅助用户建立投资观点 | `Thesis` |
| 估值 | 生成 DCF 估值模型，包含交互式 HTML 文件，支持实时拖动增长率、折现率 | `Valuation`、`Verdict` |
| 仓位 | 使用半 Kelly 计算公式，帮助用户决策仓位数量，控制回撤 | `Portfolio` |
| 复查 | 卖出前调出建仓观点，减少价格波动引起的情绪化交易，增强决策质量 | `Sellcheck` |

`skills/investment-research/` 是自包含的：SKILL.md 负责路由，每个阶段一份指南，Python 库就放在旁边。把这一个目录复制到你的 AI 工具里就能用。

## 设计原则

- **数字来自工具，不来自模型。** 任何要进入输出的数字，都要先过 `airesearch/factcontract/` 的 Fact 契约：数据陈旧、同一家公司的金额混着两种货币，
  这两种直接硬停；单位或量级异常给警告。非美元本身不拒绝，人民币股价配人民币财报照常估值。
- **不预装任何立场。** 没有内置的筛选清单，没有预设的红线，没有强制的投委会。筛选标准由你自己定义并保存；在你定义之前，intake 就是一次通用的开放搜索。
- **纯标准库。** 没有任何 pip 依赖，有 Python 3.10+ 的地方就能跑。

## 安装

让你的 AI 工具指向 `skills/investment-research/`，或者克隆后原地安装：

```bash
git clone https://github.com/Rever3I/ai-investment-research.git
cd ai-investment-research
pip install -e .
```

skill 目录自带库，单独复制它就够用。如果你的 AI 工具不会把 skill 目录加进 `sys.path`，SKILL.md 里给了那一行代码。

记录写入 `db/research.db`，首次写入时自动创建。想换位置就设 `AI_RESEARCH_DB` 环境变量。

## 配置

`config/research-profile.json` 出厂内容如下（**默认是 `en`，想要中文研报就把它改成 `zh-CN`**）：

```json
{
  "output_language": "en",
  "sizing_method": "half_kelly",
  "fixed_pct": 0.05,
  "debate_enabled": false,
  "sec_contact": "",
  "fred_api_key": "",
  "position_cap": 1.0
}
```

- `output_language` —— **研究成果用什么语言写**（thesis 正文、估值说明、结论）。填 `zh-CN` 就出中文研报，不需要另一套代码。语言标签不设白名单。注意这不影响程序自身的日志和报错，那些保持英文，方便任何人搜索排查。
- `sizing_method` —— 仓位算法：`half_kelly` / `full_kelly` / `fixed_pct` / `custom`
- `fixed_pct` —— `sizing_method` 选 `fixed_pct` 时使用的固定仓位（占总资金的比例）；`custom` 则由调用方直接给出权重
- `debate_enabled` —— 是否启用可选的分歧辩论层
- `sec_contact` —— 姓名加邮箱，例如 `"Jane Roe jane@example.com"`。SEC 要求 User-Agent 里带联系方式，不填会返回 403，美股财报就没有数据源
- `fred_api_key` —— [FRED](https://fredaccount.stlouisfed.org/apikeys) 的免费密钥，用于给折现率提供有出处的无风险利率
- `position_cap` —— 集中度上限（占总资金的比例），在算完仓位后套用。Kelly 不知道组合里还有什么，这一层判断放在这里；`1.0` 表示不设上限

用 JSON 而不是 YAML：本项目零第三方依赖，而标准库没有 YAML 解析器。

想用另一份配置就设 `AI_RESEARCH_PROFILE` 环境变量指向它。所有配置项都有可用的默认值，配置文件缺失、只写一部分、甚至存坏了，都会退回默认值并给出警告，不会中断流水线。

## 跑测试

```bash
python -m pytest -q
```

## 当前进度

五个阶段全部建成，连同它们共用的底座：记录契约、带外键约束的 SQLite 存储、Fact 契约、基于 Decimal 的股东盈余 DCF（含反向 DCF 与多情景），以及能处理多结果分布（而不只是二元情形）的 Kelly 仓位求解器。

## 数据源

适配器返回的是 `Fact` 对象而不是裸数字，所以一个数值不可能在缺少来源、单位、时点的情况下进入估值。每个 domain 是一条链：主源失败就试下一个，并把降级过程记进日志——因为一个悄悄一直失败的主源，看起来和正常工作的一模一样。

| Domain | 数据源 | 需要什么 |
| --- | --- | --- |
| `price` | Yahoo 行情（两个 host），再退到 Stooq | 无 |
| `us_equity` | SEC EDGAR XBRL 财报数据 | `sec_contact` |
| `macro` | FRED | `fred_api_key`（免费） |
| `cn_equity` | Wind | 已授权的 Wind 终端 |

```python
from airesearch.data.adapters import configure, fetch, status_report

print(status_report(configure()))     # 哪些接好了、哪些能跑
facts = fetch("us_equity", "KO")      # 净利润、折旧摊销、资本开支、股本
```

行情源零配置即可用，这是刚克隆下来时最要紧的情形。Wind 适配器按 Wind 官方文档接口写成，但**未经真实终端验证**——WindPy 随付费产品分发，无法另行安装。请把它当作起点而不是成品。

可保存的筛选 profile 设计已定、尚未实现，intake 跑的是通用搜索。
