# 你自己机器上的模型

Comodor 可以下载一个模型，把它保存在你的磁盘上，并在那里运行——无需密钥、无需账号，而且拔掉网线它照常工作。

```bash
comodor local list                       # what you can run, and what is here
comodor local get qwen2.5-coder-7b-q4    # download it, with a progress bar
comodor local use qwen2.5-coder-7b-q4    # make it the one the agent talks to
```

同样的列表在浏览器的 **Admin → Local LLM** 里，同样的下载、同样的进度和同样的按钮。

## 它是如何组装的，以及为什么它不慢

所有靠谱的实现都做同一件事——Ollama、LM Studio、llama.cpp、vLLM——Comodor 也一样：**推理运行在一个单独的进程中，该进程说一种 OpenAI 兼容的 API，而且模型在两次请求之间保持加载。**

三个理由，都与让代理保持响应有关：

**GIL。** 生成是一个漫长的 CPU 密集循环。放在 Comodor 自己的进程里跑，其他所有线程——界面重绘、某个工具收尾、事件总线——都得排在它后面等。放到另一个进程里，它就是另一个核心的事了。

**加载很昂贵，而且只该发生一次。** 从磁盘读出四个 GB 并摆好要花几秒到几十秒。按请求加载意味着每一轮都付一次这个代价；一个常驻服务器付一次，之后毫秒级应答。

**崩溃留在那边。** 一个 14B 模型的内存不足杀进程，结束的是模型服务器，而不是你的会话。代理报告一个连接错误，会话记录完好无损。

一个令人高兴的后果是几乎没有新增代码：`http://127.0.0.1:PORT/v1` 上的本地服务器*就是*一个 OpenAI 兼容端点，所以现有的提供商原样驱动它。端口在服务器启动时选定，这就是为什么 `local` 提供商在配置中不带 URL——写在那里的会在下一次就变成错的。

服务器在**你的第一条消息**时启动，而不是启动时。每次运行 `comodor` 都加载四个 GB——包括你根本没向模型提问的那些次——会是一块毫无理由的黑屏。

## 你需要什么

模型文件，由 Comodor 下载，以及一个运行它的东西。Comodor 用它找到的 whichever：

```bash
brew install llama.cpp          # macOS
winget install llama.cpp        # Windows
                                # Linux: github.com/ggml-org/llama.cpp
```

Ollama 或 LM Studio，如果任何一个已经在运行，也都能用。`comodor local
list` 在什么都没有时会直说，让你在花一小时下载之前而不是之后才发现。

## 下载

一个模型是一个到九个 GB，要经过你家里的线路，下载的一切细节都由此决定。

**它会续传。** 字节写进一个 `.part` 文件。中断它、合上笔记本、掉线——下一次 `comodor local get` 会请求服务器从那个文件结束的地方继续。浏览器显示 `Resume (37%)` 而不是 `Download`。

**它会被校验。** 每条目录记录都带一个精确的字节数和一个 SHA-256，文件在匹配之前不会被接受。这不是多余的保险：一个被截断的 GGUF *并不*明显是坏的——它能加载，然后模型开始产出胡话，而你要花一个晚上琢磨为什么一个口碑很好的模型毫无用处。校验失败的文件会被删除，而不是留下来被日后找到再半信半疑。

**它是可观看的。** 在终端里，一根进度条带四个能回答你正在问的问题的数字：

```
qwen2.5-coder-7b-q4 ━━━━━━━━━━━━━━╸────────  38.2%  1.7/4.4 GB  8.9 MB/s  0:05:12
```

在浏览器里，同样的数字显示在模型卡片的一根进度条下面，从事件流更新而不是靠轮询。

## 文件去哪里

一个目录，由这台机器上的每个项目共享——否则三个检出里的同一个模型就是同样字节的三份拷贝。

```bash
comodor local where
```

`comodor local remove <id>` 删除一个，并告诉你还回来多少空间。

## 向列表添加一个模型

列表是一个 JSON 文件，所以一个新模型是一次编辑而不是一次发布。终端和浏览器都会立即读取它。

```json
{
  "id": "my-model-q4",
  "name": "My Model 7B",
  "description": "One sentence on what it is good at, and what it is not.",
  "url": "https://huggingface.co/OWNER/REPO/resolve/main/file.gguf",
  "size": 4683074336,
  "sha256": "1664fccab734674a...",
  "context": 32768,
  "parameters": "7B",
  "quantization": "Q4_K_M",
  "needs_ram_gb": 8,
  "license": "apache-2.0",
  "good_at": ["code"],
  "tools": true,
  "vision": false
}
```

`id`、`name`、`url` 和 `size` 是必需的——其余全部可选，而你省略的任何字段都会被报告为未知而不是靠猜。这里写错一个数字，代价就是别人的一次下载和一次崩溃。

从 API 获取大小和校验和，而不是手动输入：

```bash
curl -s 'https://huggingface.co/api/models/OWNER/REPO?blobs=true' | python -c \
  "import json,sys;[print(f['rfilename'], f['size'], f.get('lfs',{}).get('sha256')) \
   for f in json.load(sys.stdin)['siblings'] if f['rfilename'].endswith('.gguf')]"
```

加载器执行两条规则：

- **只允许 `https`。** 一个模型文件在所有重要方面都是一个可执行产物，一个经由别人能在途中改写的通道取来的文件，不会因为某个目录请求了它就被放行。
- **一条坏记录不拖累整个列表。** 一个格式错误的模型被跳过，其余照常加载，因为另一个选择是一个空空如也的选择器。

Comodor 自带一份列表的副本，每天查找一次更新的版本并缓存找到的东西。没有网络时它用缓存，再不行就用自带的副本——这正是自带一份的意义所在。

## 它不会做的事

`needs_ram_gb` 会在下载开始前对照你的机器检查，一个放不下的模型会直说，而不是让你花一个小时去发现。`comodor local get --yes` 在你不同意时覆盖它。

磁盘以同样的方式检查，留出十分之一的余量：一个填满磁盘最后一个字节的下载不只是失败，它还会把机器的其余部分一起拖走。
