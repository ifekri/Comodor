# 技能

技能是一份写好的操作流程，当工作需要时智能体会遵循它。

不是你每次粘贴的提示词——而是一个文件，当情境匹配时它自己加载。

---

## 如何获取

`comodor setup` 会在最后一次性提供技能库。用方向键移动，按 **space** 勾选想要的任意多项，**enter** 会安装全部勾选项。默认什么都不勾选，而什么都不勾选时按 enter 则一无所取——你绝不会得到你没有要求的任何东西。

```
┌─ Skills ──────────────────────────────────────────────────┐
│    ☑ review        Review a change before it is committed │
│ ›  ☐ commit-style  Match the commit messages already here │
│    ☑ python-tests  Write tests the way this project does  │
└───────────────────────────────────── 2 selected ──────────┘
  ↑↓ move   space select   enter install 2   tab more   esc cancel
```

**每个技能只占一行**，因此无论技能库变得多长，整个列表都能放进一屏，而且窗口跟随光标而不是落在后面。有些描述能写满一段话——按 **tab** 会在同一帧内展开当前光标所在项的完整描述，再按一次 tab 收起。

输入即可过滤列表，数量一多这比滚动快得多。过滤时勾选状态会被保留，所以你可以缩小列表、勾选一项、清除过滤条件再勾选另一项。

没有终端时它也能接管——管道、脚本、`curl | sh`——同样的问题以编号列表的形式出现，一页一页：

| | |
|---|---|
| `1,3` 或 `1 3` | 选这些 |
| `m` / `b` | 下一页，上一页 |
| `/word` | 只显示匹配的 |
| `?7` | 读第 7 项的完整描述 |
| enter | 完成 |

编号是绝对的：无论你当前在哪一页或哪个搜索结果里，第 92 项就是第九十二个技能，所以你记下的编号就是你输入的编号。

---

## 使用一个

```bash
comodor skills browse            # what is available
comodor skills add review        # install it
comodor skills list              # what you have
```

```
/skills                          # the same, in the interface
```

从那时起，当你请求某个技能所涵盖的东西时，它会被加载，智能体会遵循它。发生时你会被告知：

```
  ▸ skill: review — Review a change for correctness before it is committed
```

一个你看不到正在被应用的技能，就是一个你无法纠正的技能。

---

## 编写一个

一个包含 `SKILL.md` 的文件夹：

```
~/.comodor/skills/our-tests/SKILL.md
```

```markdown
---
name: our-tests
description: How tests are written and run in this project.
---

# Tests in this project

- pytest, never unittest.
- One file per module, mirroring `src/`.
- Name the test after the behaviour, not the function:
  `test_an_empty_input_raises`, not `test_parse_2`.
- Never mock what you can construct.

## Running them

    uv run pytest -x -q

Not `python -m pytest` — the project needs the venv's own interpreter.
```

**description** 最重要。它是 Comodor 用来与你的请求比对、从而决定是否加载这个技能的东西，所以把它写成情境本身，而不是一个标题。

重启，或执行 `/skills`，它就在那里了。

### 打包文件

一个技能可以携带 `SKILL.md` 之外的文件：

```
~/.comodor/skills/our-tests/
  SKILL.md
  references/
    fixtures.md
    conventions.md
```

`SKILL.md` 指向它们；智能体只在需要时才读取其中一个。这让技能本身保持简短——这很重要，因为技能会被载入这一轮，一个冗长的技能无论细节是否用得上都要消耗 token。

---

## 按项目

```
./.comodor/skills/<name>/SKILL.md
```

随仓库一起提交，因此每个参与这个项目的人都会得到同样的操作流程。项目的技能与你的技能一同加载。

---

## 预算

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000
  }
}
```

`top_k` 是一轮可以加载多少个；`max_tokens` 是它们加在一起的上限。一个大到放不下的技能会被跳过，并且会告诉你跳过了哪个——这里的沉默曾经是一个真实存在的 bug：一个过大的技能悄悄挤掉了较小的那些。

---

## 管理它们

```bash
comodor skills add review taste output    # several at once
comodor skills update                     # refresh installed ones
comodor skills remove review
comodor skills list                       # with versions
```

---

## 另请参阅

- [它如何学习](learning.md) — 它自己推断出的经验，而不是你写的操作流程
- [智能体能做什么](tools.md) — 技能教它如何使用的那些工具
