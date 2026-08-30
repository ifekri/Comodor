# 从 Slack 使用

同一个代理，在你的工作区里：发送任务给它，看它工作，回答它的问题——无需打开终端。

```bash
comodor slack manifest              # the app definition to paste into Slack
comodor slack connect               # the two tokens, checked as you paste them
comodor slack pair                  # add your account
comodor slack start --background    # run it
```

大约五分钟，而且**没有需要安排的公网地址**——这正是它与 [WhatsApp](whatsapp.md) 的区别所在。

它运行的是与终端、浏览器和 Telegram 机器人相同的代理会话。从这里开始的任务会学到同样的经验，落进同一段历史。

## 为什么它简单

Slack 有两种投递事件的方式。Events API 会 POST 到一个 URL，这意味着公网 HTTPS 地址、证书和隧道——所有让 WhatsApp 变得麻烦的工作。

**Socket Mode** 把它倒了过来：应用向 Slack 索取一个 websocket 地址，然后*向外*连接。没有任何东西需要能从互联网访问，也没有需要保持更新的地址。这就是全部的窍门，也是 Slack 被归在 Telegram 一侧而不是 WhatsApp 一侧的原因。

第二件帮上忙的是**应用清单（app manifest）**。Slack 允许用一份 YAML 文档描述一个应用，所以你不必在四个设置页面里找十一个复选框，整个应用——名称、权限范围、事件、Socket Mode 已经打开——就是一次粘贴。

## 配置它

### 1. 创建应用

```bash
comodor slack manifest
```

这会打印清单和链接。在
[api.slack.com/apps](https://api.slack.com/apps?new_app=1)，选择 **From a
manifest**，选定你的工作区，粘贴，创建——然后 **Install to
Workspace**。

### 2. 两个 token

它们不可互换，而弄混它们是这件事失败的最常见原因。Comodor 会按名称拒绝放错位置的每一个，而不是让 Slack 一小时后才回一句 `invalid_auth`。

| | | |
|---|---|---|
| `xoxb-…` | **Bot token** | OAuth & Permissions。机器人做的一切都靠它 |
| `xapp-…` | **App-level token** | Basic Information → App-Level Tokens，scope `connections:write`。只负责打开 socket，别无其他 |

```bash
comodor slack connect
```

不带参数时，它会带你走完两个并逐一检查——bot token 拿去对 `auth.test` 验证，app token 则真的用它打开一个 socket。一个填错的值是一个当下的句子，而不是下周的一个谜。

### 3. 配对你的账号

```bash
comodor slack pair
```

这会打印一个六位数字代码。以私信形式发给 Comodor，你的账号就加进去了。该代码只能用一次，五分钟后过期。

**一个工作区可以有成百上千的人**，而这是一个读写你的文件的代理。因此它只应答一个固定的 Slack 用户 id 列表，其他所有人一概忽略。

```bash
comodor slack status
comodor slack forget U01234567
comodor slack forget all
```

## 它在哪里回答

**在私信里**，始终如此。

**在频道里，只在被提及时。** 一个回复共享频道里每条消息的机器人，是当天下午就被人移除的机器人。

**在叫住它的那个线程里。** 在线程里问的问题在那个线程里回答，而不是在频道里当着所有人的面回答。

它自己的消息从不回应——一个回复自己的机器人就是一个带限流的循环。

## 它能做什么，不能做什么

**默认情况下它只读取和规划，什么都不改动。** 无论终端被设置成什么，Slack 会话都被保持在计划模式（plan mode），理由与其他渠道相同：在排队时从手机上批准一条 shell 命令，是比在键盘上做同样批准时投入更少注意力的决定。

```bash
comodor slack writes on
comodor slack writes off
```

用终端命令是刻意的。一个能给自己扩大权限的机器人，只需要某人的 Slack 账号。

## 按钮

Slack 是三个渠道中最宽敞的——消息可以编辑，按钮管够——所以一条回复就是一个随答案到达而增长的消息，整个菜单装进一屏。

| | |
|---|---|
| **New chat** | 忘记目前为止的对话 |
| **History** | 重新打开一段更早的对话 |
| **Mode** | 执行、规划或聊天 |
| **Status** | 模型、文件夹、上下文、花费 |
| **Model** | 切换到另一个 |
| **Folder** | 它在哪个项目里工作 |
| **Skills** | 安装或移除一个 |
| **Rules** | 它从你的纠正中学到了什么 |
| **What it may do** | 它能不能编辑和运行 |
| **Help** | 每个东西是做什么的 |

任务运行期间唯一提供的是 **Stop**。

## 运行它

```bash
comodor slack start                # here, holding this terminal
comodor slack start --background   # detached; survives closing it
comodor slack stop
comodor slack service install      # starts at login, survives a reboot
comodor slack service show         # read the unit before trusting it
```

日志是你的配置文件旁边的 `slack.log`，追加而不是覆盖。

每个平台上都是**用户级**服务——systemd、launchd、任务计划——绝不是系统级服务。这是一个用你的凭据读写你的文件的代理，比文件主人更多的权限买不到任何东西。

## 从浏览器面板

`comodor web` → **Admin** → **From your phone** 可以在没有终端的情况下完成这里的连接、配对、启动和停止。这些控件只应答来自 Comodor 运行所在机器的请求：一个 bot token 会把它的远程控制权交给任何持有 token 的人。

## 它是如何构建的

零新增依赖。Web API 是通过本项目已有的 HTTP 客户端调用 `POST /api/chat.postMessage`，Socket Mode 则跑在为驱动 Chrome 而写的 websocket 客户端上——这就是为什么加入 Slack 没有带来任何包。

socket 循环格外小心的三件事，每一件都是让一个机器人在无人察觉的情况下悄然消失的方式：

- **每个信封都被确认。** Slack 会重新投递它没有收到确认的内容，对一个会运行命令的代理来说，一条消息变成三个回合可不只是吵闹而已。
- **`disconnect` 是家常便饭。** Slack 按计划轮换连接。把这当成故障，得到的就是一个每几小时死一次的机器人。
- **安静的工作区照样收到 ping。** 最要紧的情形——已经一小时没人给它发消息——恰恰是掉线的 socket 毁掉的那个情形。

## 它不会做的事

- 回应任何未配对的人。
- 回应它被加进的频道里的每一条消息。
- 从项目的 `.comodor/config.json` 接受 token 或允许的账号。一个能把自己作者加进那份名单的仓库就是一个后门。
- 在 `slack writes on` 之前编辑任何东西。
- 打印任何一个 token。两者都会从每条抛出的错误中被脱敏。
