# 使用你的屏幕

Comodor 可以像人一样操作机器——看屏幕、移动鼠标、点击和打字——适用于任何应用程序，而不仅仅是浏览器。

这是它能做的最强大也最危险的事情。在启用之前，请先阅读[权限模型](#permission)。

> **目前仅支持 Windows。** macOS 和 Linux 的后端尚未编写。在这些平台上，该工具完全不提供，而不是提供了却总是失败——参见[为什么它不可用](#why-it-is-not-there)。

---

## 它的样子

你可以看到整个过程。在指针移动之前，一个光环会出现在它即将点击的位置：

```
   ┌─────────────────────────────────────────┐
   │   Comodor · 14m 32s left, anywhere      │   ← the panel, top centre
   │   move the mouse to a corner to stop    │
   └─────────────────────────────────────────┘


               ╭──────────╮
               │   Save   │      ◎  ← the halo, drawn before it moves
               ╰──────────╯
                               clicking (842, 517)
```

随后指针会在大约三分之一秒内移动过去，而不是瞬间跳转，点击落点处会泛起一圈涟漪。

**这个停顿不是装饰。** 它是你仍然可以阻止它的时刻。一个瞬间跳跃并点击的光标什么也不给你留。

如果代理运行在别处——服务器、容器——同样的内容会出现在[网页界面](web.md)中：它看到的画面帧，以及它执行操作位置的标记。

---

## 启用它

两个步骤，刻意设计。哪一步都不会自动发生。

**1. 允许这个工具存在**，在 `~/.comodor/config.json` 中：

```json
{
  "computer": {
    "enabled": true
  }
}
```

在设置此项之前，模型完全不会被告知这个工具。它不在工具列表中，因此模型无法请求它，也无法被说服使用它。

**2. 允许它执行操作**，在真正需要的那一刻：

```
/computer 15m              fifteen minutes, anywhere on screen
/computer 1h this app      one hour, only while the current window is in front
/computer                  how things stand
/computer stop             end it now
```

也可以让模型来请求。它第一次需要屏幕时，你会看到：

```
  Let Comodor use your screen, mouse and keyboard?

  It will be able to see everything on your screen and to click and type
  anywhere, in any application.

  Screenshots go to the model. Whatever is on screen goes with them - open
  messages, tokens, anything visible. Redaction works on text and cannot
  read pixels.

  It will never touch a password manager, a window asking for a password,
  a locked screen, or Comodor's own window.

  To stop it at any moment: move your mouse into a corner of the screen.

  [15 minutes]  [15 minutes, this app only]  [1 hour]  [no]
```

---

## 停止它

**把鼠标移到屏幕的角落。** 这就是全部操作。

它在代理正握着指针时依然有效，这是任何键盘快捷键都无法保证的——那一刻代理可能正在某个窗口里打字。这也正是当屏幕开始自己动起来时，人们实际上会做的事。

触碰角落会结束本次运行并收回权限。再次请求就是一次新的授权。

代理自己仍可能点击角落——开始按钮、关闭框。它记得自己把指针留在了哪里，因此只有指针移动到一个没有任何程序把它放到那里的位置，才算作你操作的。

当你的双手在键盘上时，还有其他停止方式：

```
/computer stop       ends the permission
Esc                  stops the current task
```

---

## 权限

一次授权同时包含三样东西，其中没有一个是复选框。

| | |
|---|---|
| **一个范围** | 全屏幕，或按窗口标题限定某一个应用程序 |
| **一个时钟** | 授权会过期，剩余时间始终显示在屏幕上 |
| **一条退路** | 屏幕角落，在指针被驱动时依然有效 |

权限在**每一个动作之前**都会检查，而不是开始时检查一次。在授权运行中途出现的窗口也会被拦下。

### 无论如何授权都会被拒绝的对象

- 密码管理器——1Password、Bitwarden、KeePass、LastPass、Dashlane、NordPass，以及系统凭据存储。
- 标题中出现 password、passphrase、2FA 或一次性代码字样的任何窗口。
- 钱包或硬件钱包应用——MetaMask、Ledger Live、Trezor。
- 任何看起来像网上银行的东西。
- 锁定的屏幕。
- **Comodor 自己的窗口。** 一个点击驱动它的终端的代理，等于在往自己的提示符里打字。

添加你自己的：

```json
{
  "computer": {
    "never": ["Internal HR", "Payroll"]
  }
}
```

在窗口标题中的任意位置匹配，不区分大小写。

### 授权不是什么

它**绝不会写入你的配置文件**。关闭 Comodor 即结束授权。屏幕没有"始终允许"，这一缺失是刻意的。

代码仓库无法启用此功能。`computer` 不在项目 `.comodor/config.json` 可以设置的内容列表中，试图这样做的仓库会被明确拒绝。参见[安全性](safety.md#what-a-repository-may-set)。

---

## 发送给模型的内容

**截图，以及截图中一切可见的内容。** 这一点值得停下来想一想。

如果你的编辑器后面开着一个密码管理器，如果一个聊天窗口里有一条消息，如果一个 API 密钥印在终端里——它们都会出现在图片里，而图片会发给你配置的那个提供商。

Comodor 的脱敏（redaction）只作用于文本，无法读取像素。这一点没有办法绕过：这个功能本来就是"让模型看到你的屏幕"。

实用建议：

- 关闭那些你不愿意粘贴到聊天窗口里的内容。
- 使用 `/computer 1h this app`，让它只在一个窗口位于最前面时操作——不过它仍然*看得见*截图里的一切。
- 当任务是网页时，优先使用[浏览器工具](browser.md)。它返回文本而非像素，成本只是零头。

---

## 它能做什么

十七种动作，藏在一个工具背后。名称沿用 Anthropic 的，因为模型就是用这套词汇训练出来的。

### 查看

| 动作 | 作用 |
|---|---|
| `screenshot` | 当前活动显示器。`whole_desktop: true` 为所有显示器。 |
| `zoom` | 某个区域，全分辨率——它靠这个阅读小字 |
| `cursor_position` | 指针在哪里 |

### 指向

| 动作 | |
|---|---|
| `mouse_move` | 移动到某处而不点击 |
| `left_click` `right_click` `middle_click` | 可选修饰键 |
| `double_click` `triple_click` | 三连击在大多数编辑器中选中一行 |
| `left_click_drag` | 从一点拖到另一点 |
| `left_mouse_down` `left_mouse_up` | 用于拖拽无法表达的操作 |
| `scroll` | 上、下、左、右，按滚轮格数 |

### 打字

| 动作 | |
|---|---|
| `type` | 文本，按字符输入——在任何键盘布局上都正确 |
| `key` | `Return`、`ctrl+s`、`alt+Tab`、`F5`、`Page_Down`…… |
| `hold_key` | 按住某个键或组合键一段时间 |
| `wait` | 等待屏幕上的某个东西完成 |

文本**按字符输入，而不是按按键位置**。在美国键盘上 `@` 所在的按键，在法国键盘上按下会产出别的字符；而指定字符则在任何地方都产出 `@`，包括那些没有对应按键的布局。

---

## 输入了不等于到达了

应用程序会改写输入其中的内容。

Windows 11 的记事本默认开启自动更正。往里面输入 `ümlaut` 会得到 `umlaut`。内容在传输中没有丢失——三十个带变音符和非拉丁字符逐一单独发送时都能完好到达，而同一位置的 `üxqzv` 也原样未动。是应用程序改了它。

Comodor 在每次 `type` 时都会说明这一点：

```
Typed 29 characters. Applications can autocorrect or reformat what is
typed into them - take a screenshot if what arrived matters.
```

如果确切的文本很重要——密码框、配置值、提交信息——让它再看一眼。

---

## 截图及其成本

截图是这个工具发送的最昂贵的东西。

尺寸会被调整到模型能接受的范围：长边 2,576 像素，外加一个 token 预算。默认预算是 1,600 个视觉 token，在测试过的每一块屏幕上都能给出可读的图片。

| 你的屏幕 | 默认预算下 | 成本 |
|---|---|---|
| 1920 × 1080 | 1480 × 833 | ~1,590 tokens |
| 3840 × 1080 | 2068 × 582 | ~1,554 tokens |
| 3840 × 2160 | 1064 × 599 | ~836 tokens |

**不要把这个值设得太低。** "以 1280 宽度截图"这个常见建议是针对 16:9 屏幕的。在 3840 × 1080 显示器上，这意味着三倍的缩小，在那个尺寸下模型拿到的文字它读不出来——于是它开始猜而不是问。在该屏幕上实测：1280 宽时菜单标签无法辨认，2068 时完全清晰。

```json
{
  "computer": {
    "screenshot_tokens": 1600
  }
}
```

700 很便宜，在笔记本上仍然可读。4784 是模型接受的上限。

**旧截图会自动丢弃。** 对话中只保留最近两张，其余变成一行说明文字。没有这个机制，一个三十步的任务会携带近五万 token 的像素，其中绝大部分描述的是早已被点击过的屏幕。如有需要，可通过 `agent.keep_screenshots` 修改。

---

## 全部设置

```json
{
  "computer": {
    "enabled": false,
    "screenshot_tokens": 1600,
    "grant_seconds": 900,
    "travel_seconds": 0.32,
    "overlay": true,
    "never": []
  }
}
```

| 设置 | 默认值 | |
|---|---|---|
| `enabled` | `false` | 是否向模型提供这个工具 |
| `screenshot_tokens` | `1600` | 可读性与价格的权衡。最大 4784 |
| `grant_seconds` | `900` | 普通授权持续多长时间 |
| `travel_seconds` | `0.32` | 指针移动所需时间。`0` 也能用，但没法看 |
| `overlay` | `true` | 绘制光环和面板。无人在场的机器可关闭 |
| `never` | `[]` | 额外绝不触碰的窗口标题 |

---

## 为什么它不可用

如果 `computer` 不在工具之列，下列之一为真：

**平台没有后端。** 目前仅支持 Windows。该工具不被提供，而不是提供了却每次都失败——一个模型看得见却永远用不成的工具，只会诱导每一轮都浪费一次调用。

**它被关闭了。** `computer.enabled` 默认为 `false`。

直接问它：

```
/computer
```

```
no screen control: it is switched off. Set computer.enabled in your config.
```

---

## 实现原理

写给好奇的人，以及任何想把它移植到其他平台的人。

**零依赖。** 屏幕捕获是通过 `ctypes` 调用 GDI；缩小使用 `HALFTONE` 模式的 `StretchBlt`，它做平均而不是丢像素——这是可读的小字与噪点的区别。PNG 编码用 `zlib` 和 `struct`，约四十行。输入用 `SendInput`。

**DPI 感知在任何代码读取屏幕度量之前设置。** 在缩放为 125% 的显示器上——大多数 Windows 笔记本的默认值——一个未声明自己 DPI 感知的进程会被告知屏幕比实际小，于是每次点击都恰好短了一个缩放系数。原因不可见，看起来就像模型瞄不准。

**坐标转换只在一处进行。** 模型以它看到的那张图片的像素坐标作答，而那是一个缩小裁剪、原点从未告知的屏幕。`Shot.to_screen` 是唯一知道这件事的代码，因为第二份副本就是第二次搞错的机会。

**覆盖层是一个可穿透点击、永不获取焦点的窗口。** `WS_EX_LAYERED |
WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`，这样指针能到达下面的内容，键盘也停留在原处。它运行在自己的线程、自己的事件循环里，绘制失败只是少一张图，而不是少一个功能——代理在完全没有显示器的情况下也能工作。

移植到 macOS 或 Linux 意味着在 `win32.py` 旁边写一个文件，实现同样十几个函数。这一层之上的任何代码都不导入 `ctypes`。

---

## 另请参阅

- [安全与权限](safety.md) — 权限模型的其他部分
- [真实的浏览器](browser.md) — 当任务是网页时更便宜的选择
- [从浏览器使用](web.md) — 从别处观察它工作
- [成本](cost.md) — 一次长时间的桌面会话实际花费多少
