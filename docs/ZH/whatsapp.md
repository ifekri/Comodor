# 从 WhatsApp 使用

同一个代理，通过一个 WhatsApp 商业号码访问：发送任务给它，看它工作，回答它的问题——无需打开终端。

> **先读这段。** [Telegram](telegram.md) 做的是同一件事，只需大约一分钟：私信 @BotFather，粘贴一个 token。WhatsApp 需要大约二十分钟，偏技术性，而且大部分流程在 Meta 的控制台里——你需要一个 Meta 应用、一个应用密钥和一个公网 HTTPS 地址。**如果不是非用 WhatsApp 不可，就用 Telegram。**
>
> [Slack](slack.md) 是中间路线：大约五分钟，也不需要公网地址。
>
> 这些绕不过去。WhatsApp 没有等同于机器人 token 的东西，而且 Meta 是把消息投递到一个 URL，而不是让任何东西去轮询它们。唯一真正的一键版本得让每条消息都经过别人的服务器，这不是这个工具愿意做的交换。

```bash
comodor whatsapp connect              # walks you through all of it
comodor whatsapp pair                 # add your number
comodor whatsapp start --background   # run it
```

不带参数的 `connect` 是一个引导式设置：它把每一页链接出来，一次只取一个值，并在每个值到达时就地校验——token 拿去对 Meta 验证，id 检查它是不是一个 id，secret 检查它是不是一个 secret。它替你启动隧道，并且会等 Meta 的验证回调真正到达，而不是假设它到了。

它运行的是与终端、浏览器和 Telegram 机器人相同的代理会话。从这里开始的任务会学到同样的经验，出现在同一段历史里。

## 为什么它比 Telegram 需要更多配置

Telegram 给你一个 token 并让你轮询消息。WhatsApp 是 Meta 的 **Cloud API**，它的两个设计决策决定了这里的一切。

**消息是投递的，不是拉取的。** 没有长轮询。Meta 把每条入站消息 POST 到一个 URL，这意味着你的某个东西必须能从互联网上通过 HTTPS 访问。这就是额外的工作，绕不过去。

**Meta 要一个应用。** 一个商业账号、一个号码、一个访问令牌和一个应用密钥——四样住在浏览器里的东西，这就是为什么首次运行的向导把你指向这一页，而不是试图替你收集它们。

大多数项目退而求其次的选择，是用一个库通过无头浏览器驱动 WhatsApp Web。那些库需要 Node，WhatsApp 一改网页客户端就坏，而且违反账号所受的条款约束：失败模式是号码被封禁。这不是一个编程工具该递到用户手里的东西。

## 这要花多长时间

第一次大约二十分钟，对比 Telegram 的一分钟，而且大部分时间花在 Meta 的控制台而不是这里。

你**不**需要的东西：一个真实的手机号码、一种付款方式，或商业认证。添加 WhatsApp 产品会创建一个**测试号码**，免费向最多五个接收者发消息——比一个人跟自己的代理对话所需的多出四个。

## 配置它

简版就是 `comodor whatsapp connect`，它会带着你走完全程。下面是它带你走的每一步，写给想先看一遍的人。

### 1. 一个带 WhatsApp 产品的 Meta 应用

在 [developers.facebook.com](https://developers.facebook.com) 创建一个应用并添加 **WhatsApp** 产品。Meta 一开始会给你一个测试号码；真实号码之后在商业账号下添加。

你需要从那里拿到四样东西：

| | |
|---|---|
| **Phone number id** | 号码旁边的数字 id——*不是*号码本身 |
| **Access token** | 控制台自带的那个 24 小时过期。Business Settings 下的 **System User** token 不过期，该用那个 |
| **App secret** | Settings → Basic。每个 webhook 都用它签名 |
| **一个公网 HTTPS 地址** | Meta 投递消息的地方。见下文 |

```bash
comodor whatsapp connect \
    --number-id 123456789012345 \
    --token EAAG… \
    --app-secret 0a1b2c…
```

它会在保存任何东西之前先拿 token 向 Meta 验证，于是拼错是一个当下的报错，而不是下周的一个谜。

### 2. 给 Meta 一个投递去处

机器人监听 `127.0.0.1:8770`。Meta 只投递到 **HTTPS**，且不接受自签名证书，所以得有东西在它前面放一张真证书。隧道是常见的答案：不开端口、不配 DNS、不需要域名。

**如果装了 `cloudflared`，`comodor whatsapp connect` 会替你做这件事**——它启动隧道，从中读出地址，并把要粘贴的内容展示给你。想自己运行一条：

```bash
cloudflared tunnel --url http://127.0.0.1:8770
comodor whatsapp connect --url https://something.trycloudflare.com/whatsapp
comodor whatsapp webhook
```

**快速隧道每次启动都会得到一个新地址。** 设置阶段没问题，对一个要持续运行的机器人则是错的：Meta 会继续向你给它的地址投递，所以重启之后什么都不会到达，也没有任何东西解释原因。`comodor whatsapp start --tunnel` 会在地址变动时发出警告。

要一个不动的地址，就一次性建一条命名隧道——它需要一个免费的 Cloudflare 账号：

```bash
cloudflared tunnel login
cloudflared tunnel create comodor
cloudflared tunnel route dns comodor comodor-hooks.example.com
```

其他任何终结 TLS 并转发到 `127.0.0.1:8770` 的东西都以同样的方式工作。

```
  Callback URL   https://something.trycloudflare.com/whatsapp
  Verify token   Kq3nP…
```

把两者粘贴到控制台的 **WhatsApp → Configuration**，然后把应用订阅到 **messages** 字段。Meta 会立刻调用一次该 URL 来检查；机器人自己应答那个握手。

你已经在跑的反向代理也一样适用——任何终结 TLS 并转发到 `127.0.0.1:8770` 的东西。

### 3. 配对你的号码

```bash
comodor whatsapp pair
```

这会打印一个六位数字代码。从 WhatsApp 把它发给商业号码，你的号码就加进去了。该代码只能用一次，五分钟后过期。

**商业号码就是一个电话号码**，而陌生人给电话号码发消息是天经地义的事。因此它只应答一个固定列表，其他所有人得到的是**沉默**——而不是拒绝。一个回复"你不被允许"的号码，等于告诉陌生人它值得再试一次。

```bash
comodor whatsapp status         # who may talk to it
comodor whatsapp forget 15551234567
comodor whatsapp forget all
```

列表按数字比较，所以 `+1 555…`、`001 555…` 和 `1555…` 是同一个人，而不是三个。

## 它能做什么，不能做什么

**默认情况下它只读取和规划，什么都不改动。** 无论终端被设置成什么，WhatsApp 会话都被保持在计划模式（plan mode），理由与 Telegram 相同：在排队时用拇指批准一条 shell 命令，是比在键盘上做同样批准时投入更少注意力的决定。

```bash
comodor whatsapp writes on
comodor whatsapp writes off
```

这是终端命令是刻意的。一个能给自己扩大权限的机器人，只需要偷到某人的手机。

## 按钮

WhatsApp 允许**三个**二十字符的回复按钮，或一个能打开**十**行列表的按钮。这些是硬性限制——Meta 会拒绝整条消息而不是截短它——所以菜单是一个列表，而且恰好十行：

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

任务运行期间唯一提供的是 **Stop**：在这么窄的屏幕上，没有空间让一个控件灰着占位。

更长的列表——模型、技能、历史——每次分页显示八个，因为两条导航行也计入那十行。

## 两件会让你意外的事

**它不能编辑消息。** Telegram 在回答流式到达时通过重写同一条消息来实现。WhatsApp 没有编辑功能，而每 token 一条消息等于一个问题一百条通知。所以一个回合开始时说一行，工作期间偶尔说话，有了答案才发送。

**有一个以天为限的窗口。** Meta 只允许在*你*最后一条消息之后的二十四小时内发送自由格式的消息。如果一个长任务在那之后才完成，机器人无法告诉你——它会在日志里说明，而再次给它写消息会重新打开这个窗口。

## 运行它

与 Telegram 完全一致：

```bash
comodor whatsapp start                # here, holding this terminal
comodor whatsapp start --tunnel       # and bring a tunnel up with it
comodor whatsapp start --background   # detached; survives closing it
comodor whatsapp stop
comodor whatsapp service install      # starts at login, survives a reboot
comodor whatsapp service show         # read the unit before trusting it
```

日志是你的配置文件旁边的 `whatsapp.log`，追加而不是覆盖。

每个平台上都是**用户级**服务——systemd、launchd、任务计划——绝不是系统级服务。这是一个用你的凭据读写你的文件的代理，比文件主人更多的权限买不到任何东西。

## 它是如何构建的

零新增依赖。Cloud API 是通过本项目已有的 HTTP 客户端调用 `POST /messages`，webhook 是标准库里的 `http.server`。

端点会在**做事之前**先应答 Meta。Meta 对几秒内没拿到 200 的任何请求都会重试，而一个代理回合要花几分钟——一个等待完成的 webhook 会让同一条消息被投递五次。

消息 id 会被记住，因此即使重投依然到达，也不会变成第二个回合。

## 它不会做的事

- 回应任何未配对的人，或解释原因。
- 接受它无法验证的 webhook。没有 app secret 就什么也验证不了，`comodor whatsapp status` 会用黄色说明这一点。
- 从项目的 `.comodor/config.json` 接受 token、号码或允许的账号。一个能把自己作者加进那份名单的仓库就是一个后门。
- 在 `whatsapp writes on` 之前编辑任何东西。
- 打印 token。它在每条抛出的错误中都被脱敏。
