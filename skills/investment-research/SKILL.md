---
name: investment-research
description: >
  五阶段股票研究流水线：发现候选标的、写出可被证伪的投资观点、用股东盈余 DCF 和
  反向 DCF 估值、用 Kelly 公式算仓位、在想卖出时复查当初的判断变了什么。数字来自
  SEC 申报文件和实时报价，全部先过一层数据契约（陈旧数据直接中断），不来自模型记忆。
  当用户想研究一家公司、筛选标的、写投资逻辑、给股票估值、问当前价格已经隐含了多少
  增长、算仓位大小、质疑一个投资观点，或者判断当初写下的判断是否还成立时使用。
  Also use for: research a company, screen for ideas, value a stock, reverse DCF,
  position sizing, challenge a thesis, decide whether a thesis still holds.
compatibility: claude-code opencode
allowed-tools:
  - WebSearch
  - Read
  - Write
  - Bash
---

# 一人投资交易投研团队 Pro 版

按对冲基金的投研流程搭建，从选股到建仓五段闭环，财报直连 SEC 官方数据，拒绝幻觉，
不预测涨跌，只分析股票价值。

作为单个 SKILL.md 包交付，不绑定 Claude Code，也不是托管服务。装进任何支持 SKILL.md
的 AI 工具，配置你自己的市场和数据源，自己跑。

一个 skill，五个阶段。每一段交给下一段的是一份经过校验的结构化记录而不是一段文字，
所以从量化筛子来的标的和从宏观判断反推来的标的，用的是同一把尺子。

| 阶段 | 做什么 | 产出 | 指南 |
| --- | --- | --- | --- |
| 发现 | 自定义条件筛选，也支持从一个观点反推能够表达的股票 | `Candidate` | `references/intake.md` |
| 研究 | 对股票生成完整研究报告，AI 对话辅助用户建立投资观点 | `Thesis` | `references/thesis.md` |
| 估值 | 生成 DCF 估值模型，包含交互式 HTML 文件，支持实时拖动增长率、折现率 | `Valuation`、`Verdict` | `references/valuation.md` |
| 仓位 | 使用半 Kelly 计算公式，帮助用户决策仓位数量，控制回撤 | `Portfolio` | `references/portfolio.md` |
| 复查 | 卖出前调出建仓观点，减少价格波动引起的情绪化交易，增强决策质量 | `Sellcheck` | `references/sellcheck.md` |

**只读你当前所处那一个阶段的指南。** 每份几页，写清了确切的调用、失败模式，以及这一段
需要的判断。一上来把五份都读了，是把上下文花在你可能根本不会做的工作上。

阶段按请求运行，不自动串联。写完 thesis 不等于要估值；下一步花时间在哪，由用户决定。

## 安装配置

库就在这个文件旁边。把 skill 目录加进 path，一次即可：

```python
import sys
sys.path.insert(0, "<this skill's directory>")

from airesearch.config import ensure_profile
from airesearch.data.adapters import configure, status_report

print(ensure_profile())                 # creates the settings file on first run
print(status_report(configure()))
```

这会打印出哪些数据源现在能跑。行情零配置即可用。美股财报需要 `sec_contact`（姓名加
邮箱；不填 SEC 返回 403），宏观序列需要一个免费的 `fred_api_key`。

配置项存在一个 JSON profile 里。`ensure_profile()` 会在第一次运行时把它按默认值建出来
并返回路径，已存在则原样返回，不覆盖。要看当前生效的内容用 `load_profile()`。

路径取决于安装方式：源码仓库里是 `config/research-profile.json`，作为独立 skill 单独
安装时是 `~/.ai-investment-research/research-profile.json`。**永远报
`ensure_profile()` 返回的那个路径，不要自己拼一个**——把设置写到两者中错误的那一个，
就是永远不会被读取，运行随后会失败在一个看起来像网络故障的 403 上。
`AI_RESEARCH_PROFILE` 环境变量覆盖以上两者。

如果某个阶段需要的数据源没配置，说清楚缺的是哪一项设置，并打印 `profile_path()`，
让用户知道该把文件放在哪。

四个 domain，`fetch(domain, key)` 的第一个参数就是它：

| Domain | 数据源 | 需要什么 |
| --- | --- | --- |
| `price` | Yahoo 行情（两个 host），再退到 Stooq | 无 |
| `us_equity` | SEC EDGAR XBRL 财报数据 | `sec_contact` |
| `macro` | FRED | `fred_api_key`（免费） |
| `cn_equity` | 东方财富公开接口，再退到 Wind | 无 |

每个 domain 是一条链：主源失败就自动试下一个，并把降级记进日志。

## 三条贯穿所有阶段的规则

**数字来自工具，不来自模型。** 任何要进入输出的数字，都要先过 `airesearch/factcontract/`
的 Fact 契约：数据陈旧、同一家公司的金额混着两种货币，这两种直接硬停；单位或量级异常
给警告。非美元本身不拒绝，人民币股价配人民币财报照常估值。

```python
from airesearch.data.adapters import fetch
from airesearch.factcontract import verify

facts = fetch("us_equity", ticker)     # 净利润、折旧摊销、资本开支、股本
price = fetch("price", ticker)[0]
verify(facts + [price])                # 任何一项陈旧就抛错
```

不要凭记忆、也不要从来路不明的文章里报出价格、倍数或增长率。一个数字如果取不到、
验不了，就说取不到，不要自己补一个上去。

**算术不归你做。** DCF 和仓位计算在 `airesearch.valuation` 里，用 `Decimal` 精算，
并对会产生无意义结果的输入设了保护。不要心算复现它们，也不要拿自己的估计去核对。

**这里不提供任何建议。** 呈现价格假设了什么、你相信什么、什么会证明你错。不要告诉
用户买入、卖出或持有。

## 输出语言

```python
from airesearch.config import output_language
```

正文跟随这个设置。标识符不跟随：ticker、`entry_path`、情景名称、`sizing_method`、
`mode`、sellcheck 结论的首个判定词，以及 `data_sources` 里的来源字符串，都会被后续
阶段字面匹配、或按固定集合校验。每份阶段指南会各自列出它的例外。

## 数据存在哪

一个 SQLite 文件，`db/research.db`，首次写入时创建。记录是追加而不是覆盖：重新研究
一只票会保留旧的 thesis，重新估值会保留旧的数字。这份历史正是第五阶段用来对账的
东西，也是唯一能说明当初那些证伪条件写得好不好的证据。
