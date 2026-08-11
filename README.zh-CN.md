# AI 投研流水线

[English](README.md) · 简体中文

一套开放、可移植的投研流水线，以 SKILL.md 形式交付——不绑定 Claude Code，也不是托管服务。装进任何兼容 SKILL.md 的宿主（运行技能的 AI 工具），配置你自己的市场和数据源，自己跑。

## 分层

1. **research-intake** —— 双入口（筛选优先 / 论点优先），产出 `Candidate` 记录
2. **research-thesis** —— 深度研究，产出 `Thesis` 记录
3. **research-valuation** —— DCF / 可比公司 / 情景分析，产出 `Valuation` 记录和交互式 HTML
4. **research-debate** —— 可选的风险与分歧层，产出 `Verdict` 记录
5. **research-portfolio** —— 仓位测算（默认半 Kelly），产出 `Portfolio` 记录
6. **research-sellcheck** —— 卖出时按需触发的 thesis 复查，产出 `Sellcheck` 记录

每一层交给下一层的是一份经过校验的结构化记录，而不是一段文字。所以不管标的是从量化筛子来的，还是从一个宏观判断反推来的，走的都是同一条流水线、同一把尺子。

## 设计原则

- **数字来自工具，不来自模型。** 任何要进入输出的数字，都要先过 `skills/_lib/factcontract/` 的 Fact 契约：数据陈旧直接硬停，单位或量级异常给警告。
- **不预装任何立场。** 没有内置的筛选清单，没有预设的红线，没有强制的投委会。筛选标准由你自己定义并保存；在你定义之前，intake 就是一次通用的开放搜索。
- **纯标准库。** 没有任何 pip 依赖，有 Python 3.10+ 的地方就能跑。

## 安装

各层技能会 import 共享库 `skills/_lib/`，所以仓库根目录必须在你的 AI 工具运行 Python 时可被导入。克隆后原地安装：

```bash
git clone https://github.com/Rever3I/ai-investment-research.git
cd ai-investment-research
pip install -e .
```

只把某一个 `skills/<layer>/` 目录复制进宿主的 skills 文件夹是不够的——那一层的代码引用了 `skills._lib`，共享库必须跟着走。请让宿主指向整个仓库，或按上面的方式安装。

记录写入 `db/research.db`，首次写入时自动创建。想换位置就设 `AI_RESEARCH_DB` 环境变量。

## 配置

`config/research-profile.json` 出厂内容如下（**默认是 `en`，想要中文研报就把它改成 `zh-CN`**）：

```json
{
  "output_language": "en",
  "sizing_method": "half_kelly",
  "fixed_pct": 0.05,
  "debate_enabled": false,
  "position_cap": 1.0
}
```

- `output_language` —— **研究成果用什么语言写**（thesis 正文、估值说明、结论）。填 `zh-CN` 就出中文研报，不需要另一套代码。语言标签不设白名单。注意这不影响程序自身的日志和报错，那些保持英文，方便任何人搜索排查。
- `sizing_method` —— 仓位算法：`half_kelly` / `full_kelly` / `fixed_pct` / `custom`
- `fixed_pct` —— `sizing_method` 选 `fixed_pct` 时使用的固定仓位（占总资金的比例）；`custom` 则由调用方直接给出权重
- `debate_enabled` —— 是否启用可选的分歧辩论层
- `position_cap` —— 集中度上限（占总资金的比例），在算完仓位后套用。Kelly 不知道组合里还有什么，这一层判断放在这里；`1.0` 表示不设上限

用 JSON 而不是 YAML：本项目零第三方依赖，而标准库没有 YAML 解析器。

想用另一份配置就设 `AI_RESEARCH_PROFILE` 环境变量指向它。所有配置项都有可用的默认值，配置文件缺失、只写一部分、甚至存坏了，都会退回默认值并给出警告，不会中断流水线。

## 跑测试

```bash
python -m pytest -q
```

## 当前进度

六层全部建成，连同它们共用的底座：记录契约、带外键约束的 SQLite 存储、Fact 契约、基于 Decimal 的股东盈余 DCF（含反向 DCF 与多情景），以及能处理多结果分布（而不只是二元情形）的 Kelly 仓位求解器。

尚未完成的是市场数据适配器（SEC EDGAR、Wind、FRED、新闻舆情）——所以目前各层的数字来自宿主提供的搜索，经 Fact 契约核验后使用。可保存的筛选 profile 设计已定、尚未实现，intake 跑的是通用搜索。
