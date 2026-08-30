# 提问

歧义有两种糟糕的结局。智能体选定一种理解，把错误的东西构建出来，让你付出一轮评审的代价。或者它用散文式的语言逐个提问，你花四个回合才敲定本可以一屏之内敲定的事情。

Comodor 走第三条路。当一个请求可以有多种读法时，智能体会先梳理出*所有*它不确定的地方，然后以一份简短的选择题表单呈现给你——三四个问题，大约十五秒内答完，在任何一行代码被写下之前。

对"给 web server 加上 rate limiting"这个请求，它先读了十个文件，然后提出这个问题：

```
┏━  3 questions  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                                                          ┃
┃    ☐  Client identity   ☐  Over-limit   ☐  Scope                         ┃
┃                                                                          ┃
┃  How should clients be identified for rate limiting?                     ┃
┃                                                                          ┃
┃   › ☐ By IP address (recommended)                                        ┃
┃        The server already reads client_address for the loopback check.   ┃
┃     ☐ By token                                                           ┃
┃     ☐ Something else                                                     ┃
┃                                                                          ┃
┃    0 of 3 answered                                                       ┃
┃                                                                          ┃
┗━━━━━━━━━━━━━━  ↑↓ move · ←→ question · space pick · enter next · esc  ━━┛
```

注意第一个选项的第二行。它在提问之前已经读过 `web/server.py`，而这个问题问的正是那次阅读无法解决的决定。

## 在终端中

```
left / right      previous and next question
up / down         move within the options
space             pick — and toggle, when several answers may apply
enter             pick, then jump to the next unanswered question;
                  on the last one, send
ctrl+s            send from anywhere
escape            close without answering
```

标签条会为每个问题标注一个记号，所以你可以一眼看出哪些还没有回答，而不必逐个查看。

## 在浏览器中

同样的表单，以对话框的形式。点击标签或使用方向键，点击一个选项，然后按 **Send**。`Escape` 关闭它。

## 最后一行

每个问题都以 **Something else** 结尾，并附一个可输入的文本框。它由 Comodor 添加，而不是由模型添加，模型也无法移除它——这一行存在的全部意义，就在于它涵盖模型没想到的东西。在其中输入会替换掉已选中的任何选项，而选中某个选项则会清空已输入的内容，因此一个问题永远不会带回两个相互矛盾的答案。

## 跳过

发送一个还有问题未作答的表单完全没问题，而且这与直接关闭表单不是一回事。智能体会确切地被告知你搁置了哪些问题，也就是说你并没有约束它们——于是它自行决定这些事项，并说明自己的决定。

完全关闭表单（**Not now**，或 `escape`）则告诉智能体带着合理的默认值继续，并且**不要再问**。对一个刚刚关掉第一份表单的人再递上第二份，正是让这类功能招人厌恶的行为。

## 它不问的时候

这是设计使然，不是偶然：

- 任何它可以通过阅读项目弄清楚的事。它先读。
- 允许继续的许可。那是审批提示的职责。
- 把它的计划复述给你确认。
- 有明显默认值的选择。它直接采用默认值，并告诉你它这么做了。

## 限制

最多四个问题，每个问题最多四个选项——外加一行自己填写的选项，它不计入四个之内。再多就不是快速表单，而是一场访谈；一个需要六个答案的智能体，应该先要那四个要紧的，其余的自己解决。

表单会等待三十分钟。之后它会带着未回答的状态返回，智能体继续工作，这样一台无人值守的机器上开着的表单就无法把一次运行无限期地拖住。

## 对其他模型

这个工具叫 `ask`，风险等级为 `SAFE`，也就是说它在 Plan 模式下同样可用——规划正是歧义咬人最疼的时候。

模型使用它的积极程度各有不同。测试过的每个模型都会在请求明显需要提问时提问、不需要时保持安静，但如果你的模型在凭猜测行事，在你自己的消息里说一句 *"ask me about anything you need to decide first"* 就能立刻解决。
