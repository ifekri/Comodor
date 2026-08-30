# 在 Docker 中

代理、它的浏览器以及它需要的一切，装进一个容器。

```bash
git clone https://github.com/ifekri/Comodor.git
cd Comodor
export ANTHROPIC_API_KEY=…        # or OPENAI_API_KEY, OPENROUTER_API_KEY, …
docker compose up
```

它会在第一次构建镜像，然后打印地址：

```
  Comodor is at  http://127.0.0.1:8765/?token=…
  Working in     /work
```

打开链接。每次运行都会生成新的 token，所以请使用*本次*运行的那个。

或者无需克隆任何东西：

```bash
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -e ANTHROPIC_API_KEY \
  -v "$PWD:/work" \
  ghcr.io/ifekri/comodor:latest
```

---

## 这里密钥不是可选项

浏览器界面没有输入密钥的地方，因此没有密钥时容器会说明缺什么然后停止，而不是提供一个在第一个任务上就会失败的 URL。

Compose 会把你 shell 中设置的以下变量透传进去，不会写入镜像或 compose 文件：

```
ANTHROPIC_API_KEY   OPENAI_API_KEY   OPENROUTER_API_KEY   DEEPSEEK_API_KEY
GOOGLE_API_KEY      GROQ_API_KEY     XAI_API_KEY          MISTRAL_API_KEY
XIAOMI_API_KEY
```

不想留在 shell 历史里？把它放进 compose 文件旁边的 `.env` 文件——compose 会读取它，而且它已被 git 忽略。

---

## 它在哪里工作

代理能触及的一切都在 compose 文件旁边的 `work/` 文件夹里。想指向别处：

```yaml
volumes:
  - "/path/to/your/project:/work"
```

它学到的东西——大脑（brain）、你的纠正、会话记录——存放在一个命名卷（named volume）中，因此能在 `docker compose down` 之后保留，而 `docker compose down -v` 会将其清除。

---

## 谁能访问它

```yaml
ports:
  - "127.0.0.1:8765:8765"
```

**左边的 `127.0.0.1` 就是整个安全模型。** 去掉它，端口就会暴露在机器的每个网络接口上——而这个端口是一个 shell。

在容器内部，Comodor 绑定 `0.0.0.0`，这并非疏漏：容器有自己的网络命名空间（network namespace），所以在容器内绑定回环地址会对运行它的机器隐藏该端口。谁实际能访问它由端口的发布方式决定，横幅（banner）里会说明这一点。

---

## 容器可以做什么

```yaml
cap_drop: [ALL]
security_opt:
  - no-new-privileges:true
```

它会运行 shell 命令，所以容器就是挡在这些命令与你的机器之间的东西。它不会被给予任何不需要的东西，并以非 root 用户运行。

---

## 锁定版本

```yaml
args:
  COMODOR_VERSION: ""
```

默认锁定版本，因此重新构建是可复现的。想要最新发布版：

```bash
docker compose build --build-arg COMODOR_VERSION=
```

---

## 在其中运行别的东西

```bash
docker compose run --rm comodor comodor doctor
docker compose run --rm comodor sh
```

不带参数，或参数以短横线开头，表示"用这些选项运行网页界面"。其他任何内容都作为要运行的命令。

---

## 容器里没有什么

**你的屏幕。** [桌面控制](computer.md)驱动的是 Comodor 运行其上的那台机器，而在容器里那是一台没有显示器的机器。该工具在那里不提供。

[浏览器](browser.md)可以工作——Chromium 及其字体都在镜像里。

---

## 如果它启动不了

**`localhost:8765` 上什么都没有** — 检查端口是否已发布：`docker compose ps`。

**立即退出** — 读一下日志。几乎总是没有配置模型提供商；消息会说明要设置什么。

**`exec /usr/local/bin/comodor-start: no such file or directory`** — 这是 CRLF 换行签出的仓库。该分支已通过 `.gitattributes` 修复；如果遇到，请执行 pull。

---

## 另请参阅

- [从浏览器使用](web.md) — 你将要使用的界面
- [安全性](safety.md) — 代理在容器内可以做什么
