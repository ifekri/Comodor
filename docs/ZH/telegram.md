# 从手机使用

Comodor 可以通过 Telegram 机器人驱动：发送任务给它，看它工作，回答它的问题，并停止它——无需打开终端。

**首次运行的设置会问到这个。** 六个问题中的最后一个会提出连接一个机器人，当场用 Telegram 校验 token，并在向导结束之前完成你的账号配对。如果你当时选择了 *Not now*，或者你正在配置一台已经设置好的机器：

```bash
comodor telegram connect <token>   # a bot from @BotFather
comodor telegram pair              # add your account
comodor telegram start             # run it
```

它运行的是与浏览器界面相同的代理会话。一切都通过按钮；打字留给任务本身。

## 获取一个机器人

在 Telegram 上私信 [@BotFather](https://t.me/botfather)，发送 `/newbot`，给它起一个名字和一个以 `bot` 结尾的用户名。它会回复一个 token：

```
1234567890:AAF…
```

```bash
comodor telegram connect 1234567890:AAF…
```

## 配对

**机器人的用户名是公开的。** 任何发现它的人都可以给它发消息，而这个机器人能读你的文件。因此它只应答一个固定的数字 Telegram 用户 id 列表，其他任何人都一概不理。

```bash
comodor telegram pair
```

这会打印一个六位数字代码。在 Telegram 上把它发给你的机器人，你的账号就加进去了。该代码只能用一次，五分钟后过期。

其他所有人得到的是**沉默**——而不是拒绝。一个回复"你不被允许"的机器人已经告诉了陌生人：它存在、它是一个 Comodor、而且有一份值得挤进去的名单。

```bash
comodor telegram status         # who may talk to it
comodor telegram forget 12345   # revoke one account
comodor telegram forget all     # revoke everybody
```

## 它能做什么，不能做什么

**默认情况下它只读取和规划，什么都不改动。** 无论终端被设置成什么，Telegram 会话都被保持在计划模式（plan mode）。

这是刻意的。在手机上、在排队时、用拇指批准一条 shell 命令，是比在键盘上做同样批准时投入更少注意力的决定——而后果是完全一样的。

```bash
comodor telegram writes on      # let it edit files and run commands
comodor telegram writes off
```

打开写入之后它仍然会先询问，批准就是聊天里的一个按钮：

```
Comodor wants to run
  npm test

  ✓  Yes, once
  ✓✓ Yes, and stop asking this session
  ✗  No
```

最重的承诺永远不会是拇指下的第一个按钮——在手机上它们挨得很近，而"总是"是无法撤销的。

## 按钮

`/start` 会回答模型、文件夹以及它被允许做什么，下面紧跟着设置。它们出现在第一屏，而不是藏在 *Settings* 按钮后面，因为机器人被指向哪里是任何人首先想知道、也首先想改动的事。

| | |
|---|---|
| **New chat** | 忘记目前为止的对话 |
| **History** | 重新打开任何一段更早的对话，完整地 |
| **Stop** | 打断正在运行的内容——在它运行期间取代 *New chat* |
| **Mode** | 执行、规划或聊天，每一种都写明 |
| **Status** | 模型、文件夹、上下文、花费 |
| **Model** | 提供商提供的每个模型；点按切换 |
| **Folder** | 它被限定在哪个项目里 |
| **Skills** | 从库中安装或移除一个 |
| **Rules** | 它从你的纠正中学到了什么，学了多少条 |
| **Settings** | 其余的——花费，以及它可以做什么 |
| **Help** | 每个东西是做什么的，不用离开聊天 |

当代理需要一个决定时，它也用按钮来问——与它在终端里会问的相同问题，一屏一个，另有 **Write my own** 应对它没想到的情况。

超过一屏的列表——模型、技能、历史——每次分页显示六个，带 **Previous** 和 **Next**。Telegram 可以欣然渲染八十个按钮，但没有人会去翻它们。

## 运行它

三种方式，按你希望它持续多久排序。

```bash
comodor telegram start                # here, holding this terminal
comodor telegram start --background   # detached; survives closing the terminal
comodor telegram service install      # starts at every login, survives a reboot
```

**前台运行**会占住终端并显示它在做什么。设置期间用这一个，出问题时也回到这一个。

**后台运行**是同一个进程，与启动它的终端脱离，写日志而不是写屏幕。关闭终端、注销、结束会话——都带不走它。

```bash
comodor telegram stop        # end it
comodor telegram status      # is it running, since when, and as which pid
```

日志是你的配置文件旁边的 `telegram.log`，它是追加而不是覆盖——机器人昨晚为什么停了，答案就在重启会把它们抹掉的那些行里。

**开机自启**是操作系统的职责，不是我们的：程序为自己启动的任何东西都活不过机器重启。

```bash
comodor telegram service show        # read the unit before trusting it
comodor telegram service install
comodor telegram service uninstall
```

| | |
|---|---|
| Linux | `~/.config/systemd/user` 中的 systemd **user** unit |
| macOS | `~/Library/LaunchAgents` 中的 LaunchAgent |
| Windows | 一个在登录时运行的计划任务（Task Scheduler task） |

三者全部是用户级服务，绝不是系统级服务。系统服务以 root 或 SYSTEM 身份运行，而这是一个用你的凭据读写你的文件的代理——比文件主人更多的权限买不到任何东西，却在出错时付出一切代价。

`service show` 在 `service install` 写入之前打印 unit。不应该有人被要求信任一个从未见过的守护进程定义。

文件夹在三者中都很重要：代理只在它启动时所在的目录里读写，那也是机器人将要工作的目录。

## 它是如何构建的

零新增依赖。Bot API 就是循环里的 `getUpdates` 和 `sendMessage`，走的是本项目已有的 HTTP 客户端——
`python-telegram-bot` 会成为 wheel 包里最大的东西，就为了这个。

回复按定时器编辑，而不是每个 token 编辑一次。Telegram 对每次编辑收取一次往返并限流，因此按 token 编辑会产出一个被限流到最后一口气全部到达的消息。

机器人持有一个更新偏移量（update offset），并随处理推进它。没有它，重启会把机器人收到过的每条消息重放一遍——对一个会运行命令的代理来说，这可不只是吵闹而已。

## 它不会做的事

- 回应任何未配对的人，或解释原因。
- 从项目的 `.comodor/config.json` 接受 token 或允许的账号。一个能把自己作者加进那份名单的仓库就是一个后门，而且与浏览器或屏幕不同，屏幕上不会有任何东西让你看见这件事正在发生。
- 在 `telegram writes on` 之前编辑任何东西。
- 打印 token。它出现在每个 Bot API URL 里，所以抛出的每条错误都已将它剔除。
