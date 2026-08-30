# 真实的浏览器

不是一个网页抓取器，而是机器上实际安装的浏览器——它能运行 JavaScript、保留 Cookie，并且可以登录。

---

## 使用什么浏览器

Chrome、Chromium、Edge 或 Brave，取决于机器上安装了哪一个。**不会下载任何东西。** 它会在一个独立的配置文件（profile）中启动浏览器——该配置未登录任何账号——并在会话结束时将其关闭。

如果以上都未安装，`browse` 会退回到一个文本浏览器，它仍然能回答关于页面的大部分问题。两者都叫 `browse`，因为让模型在两个名为"浏览器"的工具之间做选择，是在浪费一个本不该浪费的回合。

---

## 返回什么

不是截图。而是标题、可读文本，以及**屏幕上实际可见控件的编号列表**：

```
  Sign in — Example
  ─────────────────────────────────────────────
  Sign in to your account. New here? Create one.

  [1]  textbox   Email
  [2]  textbox   Password
  [3]  button    Sign in
  [4]  link      Forgot your password?
```

模型按编号对控件进行操作。该列表会过滤为可见的、有名称的、在屏幕上的且不重复的控件——这比无障碍树（accessibility tree）小得多，而且经实测，也比同一页面的截图更小。

只有当问题是视觉性质的——布局、样式、图表——才会使用截图，因为图片每次的成本都一样，而且无法精简。

---

## 操作动词

| | |
|---|---|
| `open` | 打开一个 URL |
| `click` | 按编号点击一个控件 |
| `type` | 按编号在字段中输入 |
| `scroll` | 向上或向下滚动 |
| `back` | 返回上一页 |
| `read` | 重新读取页面，在页面发生变化之后 |
| `look` | 截图，当问题关乎页面外观时 |
| `script` | 运行 JavaScript 并返回其值 |

---

## 观察它工作

```json
{ "browser": { "headless": false } }
```

显示可见窗口，这样你就能看到它在做什么。

> 这个设置曾一度被忽略——`browser` 此前没有被注册为配置区块，所以所有 `browser` 设置都默默无效。已在 0.9.0 中修复。

---

## 使用你已登录的会话

与其交出你的配置文件，不如以 DevTools 端口启动你自己的浏览器，然后让 Comodor 连接它：

```bash
chrome --remote-debugging-port=9222
```

```json
{ "browser": { "port": 9222 } }
```

它会连接到那个浏览器，并使用其中已有的标签页和 Cookie。用完之后请关闭该端口——你机器上的任何程序都可以使用它。

---

## 全部设置

```json
{
  "browser": {
    "executable": "",
    "headless": true,
    "width": 1280,
    "height": 800,
    "port": 0
  }
}
```

| | |
|---|---|
| `executable` | 指定某个浏览器。留空表示在常见位置查找 |
| `headless` | 默认无头（不可见），因此不会抢占焦点 |
| `width`, `height` | 窗口尺寸 |
| `port` | 连接到你自行启动的浏览器，而不是新启动一个 |

代码仓库无法设置其中任何一项——`browser.executable` 指定的是要启动的二进制文件。[安全性](safety.md#what-a-repository-may-set)。

---

## `browse` 还是 `web_fetch`？

| | |
|---|---|
| `web_fetch` | 页面是一份文档。将其提炼为文本。成本低 |
| `browse` | 页面是一个应用。需要 JavaScript、登录或点击 |

模型被告知优先使用 `web_fetch`，当它行不通时再使用 `browse`。

---

## 在容器中

Docker 镜像自带 Chromium 以及配套的渲染字体。当容器的 seccomp 配置阻止用户命名空间（user namespaces）时，Chromium 自带的沙箱无法在容器内启动，因此 Comodor 会检测到这一点并在禁用内部沙箱的情况下重试——同时保留容器本身的隔离限制，那才是真正的安全边界。[Docker](docker.md)。

---

## 实现原理

通过手写的 WebSocket 使用 Chrome DevTools Protocol。零依赖：RFC 6455 的帧协议只有约一百行代码，与 HTTP 客户端和 SSE 读取器一样，都是软件包的一部分。

---

## 另请参阅

- [代理能做什么](tools.md) — 其他工具
- [使用你的屏幕](computer.md) — 当任务不是网页时
- [成本](cost.md) — 为什么它返回文本而不是图片
