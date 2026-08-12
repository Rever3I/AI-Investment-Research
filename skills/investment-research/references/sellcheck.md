# 阶段 5 —— 复查：建仓之后什么变了

在用户开始考虑卖出时才跑。背后刻意没有任何监控——不轮询、不告警、不定时扫描。持续
监控考虑过，被放弃了：它产出的是一串会训练你去忽略它的通知，而真正要紧的那一刻，是
你已经在重新考虑的那一刻。

## 它回答的问题

不是「我该不该卖」。那是用户的决定，这一段不做。

问题是**三件事里发生了哪一件**，因为对应的正确反应完全不同，而在当下它们又极容易混淆：

`facts_changed` —— 世界朝着不利于这个论证的方向动了。某条证伪条件触发了，thesis 依赖
的某个数字来得不一样，竞争对手做了 thesis 说他们做不到的事。这是「卖出」这个决定能被
当初的推理支持的情形。

`judgment_changed` —— 事实大致如预期，是你现在对它们的读法变了。有时那是学习。有时
那是价格在动、故事自己重新排列去迎合它。值得把它是什么如实点出来，因为从内部感受，
这两种一模一样。

`still_holds` —— 没有实质性的变化。这个仓位是难受，不是坏掉。直说这一点；难受不是信息。

## 读回当初的论证

```python
from airesearch.data.thesis_store import get_thesis, get_thesis_for_candidate
from airesearch.data.sellcheck_store import list_sellchecks_for_thesis

thesis = get_thesis(thesis_id)
history = list_sellchecks_for_thesis(thesis.id)   # earlier rechecks, newest first
```

写新的之前先读之前几次复查。一份被复查过三次、每次都离原始论证再远一点的 thesis，
和一份今天才失效的 thesis 是完全不同的处境——而只有历史能看出这一点。

## 对账

按 thesis 写下来的顺序，一节一节过，对每一节说清现在什么是真的、以及是否有出入：

1. **先看证伪条件。** 它们当初就是为了让此刻变简单才写下来的。有没有哪一条触发了？
   一条已经触发、然后被绕过去的证伪条件，是最需要报出来的一件事。
2. **变异认知。** 市场当初据说漏掉的那个东西，现在还漏着，还是已经被定价了？一个
   edge 已经被市场认识到的 thesis 是成功了而不是失败了，那是另一种卖出理由。
3. **风险。** 列出来的那些里哪些兑现了，而真正造成伤害的那些里，哪些当初压根不在
   名单上？后一组是更有用的发现——它说明了这份 thesis 当初是怎么搭起来的。
4. **数字。** 把论证所依赖的数字重新取一遍。每个数字都要过 Fact 契约；拿记忆里的
   数字去对比，不算对比。

## 保存

```python
from airesearch.data.schema import Sellcheck
from airesearch.data.sellcheck_store import save_sellcheck

sellcheck = Sellcheck(
    thesis_id=thesis.id,
    trigger="user_initiated",
    diff_summary="facts_changed: export licence revoked; the TAM assumption "
                 "the thesis rested on no longer applies.",
    rechecked_at=today_iso,
)
row_id = save_sellcheck(sellcheck)
```

`diff_summary` 以 `facts_changed`、`judgment_changed`、`still_holds` 三者之一开头，
后面接具体是什么。开头那个词是让一连串复查日后能被快速扫读的东西；后面的细节才是让
每一次复查有用的东西。

每一次复查都保留。时间长了，这个序列是唯一能说明当初那些证伪条件写得好不好的证据，
而这正是下一份 thesis 写得更好的方式。

## 输出语言

正文跟随 `output_language()`。不要翻译 `diff_summary` 开头那个判定词——
`facts_changed` / `judgment_changed` / `still_holds` 是让这份历史跨语言可扫读的标记。

## 收尾

先说是三者中的哪一个，以及支持它的证据。然后是证伪条件的状态，然后是那些变了、
但当初没人列出来的东西。

不要建议卖出或持有。呈现什么动了、什么没动；决定和仓位都是用户的。
