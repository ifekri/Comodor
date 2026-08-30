# MCP 服务器

Model Context Protocol（模型上下文协议）是一种让工具向代理描述自己的方式。Comodor 支持该协议，因此任何提供 MCP 服务器的系统都会变成代理可以使用的东西。

---

## 添加一个

```bash
comodor mcp catalogue          # servers Comodor can set up for you
comodor mcp add filesystem     # one of them
comodor mcp list               # what you have, and what each offers
```

目录中没有的：

```bash
comodor mcp custom notes -- npx -y @some/mcp-notes
comodor mcp remote github https://mcp.example.com/sse
```

然后在信任它之前，先确认它确实能工作：

```bash
comodor mcp test notes
```

```
  notes            started in 0.8s
    create_note    Create a note with a title and body
    search_notes   Find notes by text
    delete_note    Delete a note by id
```

---

## 启用与禁用

```bash
comodor mcp enable notes
comodor mcp disable notes
comodor mcp remove notes       # forget it entirely
```

```
/mcp                           # the same, in the interface
```

被禁用的服务器不会启动，它的工具也不会被提供。

---

## 它们和其他工具一样

服务器提供的任何东西都会与内置工具并列出现，并经过**完全相同的权限门槛**。一个写文件的 MCP 工具会像 `write_file` 那样询问。这里没有后门。

---

## 项目只能声明，不能启用

仓库的 `.comodor/config.json` 可以列出它使用的服务器：

```json
{
  "mcp": {
    "servers": {
      "project-db": { "command": "npx", "args": ["-y", "@acme/db-mcp"] }
    }
  }
}
```

这很有用：新人克隆仓库后就能看到项目需要什么。

**它们到达时是关闭的。** 命名一个服务器只是建议；启动一个则要在你的机器上运行一条命令，那是你的决定。看过之后启用它：

```bash
comodor mcp enable project-db
```

项目完全不能设置 `mcp.enabled` 这个总开关。
[安全性](safety.md#what-a-repository-may-set)。

---

## 传输方式

| | |
|---|---|
| **stdio** | 由 Comodor 启动并通过管道通信的命令。常见方式 |
| **Streamable HTTP** | 已经在别处运行的服务器，通过 HTTP 访问 |

两者都在软件包内实现——都不引入依赖。

---

## 当某个服务器行为异常时

无法启动或耗时过长的服务器会被报告并跳过。
它不会把整个会话一起拖垮。

```bash
comodor mcp test <name>        # start it and see
comodor doctor                 # includes every configured server
```

---

## 另请参阅

- [代理能做什么](tools.md) — 这些服务器加入的内置工具
- [安全性](safety.md) — 它们要经过的门槛
