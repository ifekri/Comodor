# من الطرفية

كل أمر وكل علَم، مع شيء يمكنك لصقه.

```bash
comodor help              # the written help page
comodor help computer     # one topic in more detail
```

---

## التثبيت والتحديث

```bash
curl -fsSL get.comodor.ai | sh     # macOS, Linux, BSD
```

```powershell
irm get.comodor.ai | iex          # Windows
```

لا يسمّي `get.comodor.ai` أي ملف: إنه يقرأ أي عميل يسأل ويجيب بالمثبّت الذي
يستطيع ذلك العميل تشغيله. وحدّث السطر نفسه تثبيتًا قائمًا. أو، بعد وجوده على
جهازك:

```bash
comodor update --check    # what is out there
comodor update            # move to it
```

في [البداية](getting-started.md#1-install) الباقي — مديرو الحزم، وما تقبله
المثبّتات.

---

## تشغيله

```bash
comodor                              # the interface
comodor --demo                       # the interface, offline, no key needed
comodor --resume                     # reopen the last session
comodor --resume 2026-08-22-a4f1     # reopen one by id
comodor --cwd ~/projects/api         # work somewhere other than here
comodor --model claude-sonnet-5      # a different model, this run only
comodor --mode plan                  # start read-only
```

### الخيارات

| | |
|---|---|
| `--provider NAME` | `openrouter`، `anthropic`، `openai`، `ollama`، … |
| `--model ID` | تجاوز النموذج لهذا التشغيل |
| `--mode act\|plan\|chat` | plan للقراءة فقط؛ chat بلا أدوات |
| `--no-loop` | الإجابة مرة واحدة بدل العمل حتى الانتهاء |
| `--cwd PATH` | المجلد الذي يجوز له لمسه |
| `--theme NAME` | `ember`، `midnight`، `matrix`، `mono` |
| `--ascii` | حدود ASCII |
| `--no-mouse` | ترك الفأرة للطرفية |
| `--resume [ID]` | الجلسة الأخيرة، أو واحدة بعينها بمعرّفها |
| `--demo` | مزوّد دون اتصال مخطط له مسبقًا |
| `--version` | أي إصدار هذا |
| `-h`، `--help` | صفحة المساعدة المكتوبة |

لا يُكتب أي من هذه إلى ملف إعدادك. وتنطبق على تشغيل واحد. ولكي يستقر تغيير،
استخدم `/save` داخل الواجهة أو عدّل ملف الإعداد —
[الإعداد](configuration.md).

---

## `comodor run` — مهمة واحدة، بلا واجهة

```bash
comodor run "fix the failing test in tests/test_parser.py"
comodor run "add type hints to src/parser.py" --yes
comodor run "what does this project do?" --json
comodor run "refactor the parser" --max-steps 40
```

| | |
|---|---|
| `--yes` | الموافقة تلقائيًا على الكتابات والأوامر |
| `--json` | نتيجة يقرؤها الجهاز على stdout |
| `--max-steps N` | تجاوز حد الخطوات لهذا التشغيل |

دون `--yes` سيطلب ذلك، على stderr، ويرفض بدل أن يفترض إذا لم يكن هناك ما يجيب.
وهذا مقصود: السكربت الذي يوافق على نفسه بصمت هو سكربت يفعل شيئًا لم تتوقعه في
الثالثة فجرًا.

يعطيك `--json`:

```json
{
  "text": "Fixed. The parser raised on empty input rather than returning [\"\"] …",
  "ok": true,
  "stopped": "done",
  "steps": 6,
  "tool_calls": 11,
  "error": "",
  "usage": {
    "input_tokens": 18422,
    "output_tokens": 640,
    "cost_usd": 0.031
  },
  "elapsed": 24.71
}
```

ويقول `stopped` لما انتهى — إحدى هذه:

| | |
|---|---|
| `done` | قرر أنه انتهى |
| `max_steps` | اصطدم بـ `agent.max_steps` |
| `budget` | اصطدم بـ `agent.max_cost_usd` أو `agent.max_seconds` |
| `cancelled` | مقاطعتك له |
| `error` | حدث خلل ما؛ ويقول `error` ما هو |

يكون `ok` صحيحًا لـ `done` و`max_steps` — فنفاد الخطوات ليس فشلًا، بل سقف يؤدي
وظيفته — لذا افحص `stopped` أيضًا إن احتجت التمييز:

```bash
comodor run "update the changelog for this release" --yes --json > result.json
jq -e '.stopped == "done"' result.json
```

ويتعلم حتى من تشغيل بلا رأس. فالتصحيح الذي تجريه لاحقًا يعلّمه الدرس نفسه الذي
يعلّمه إياه تشغيل تفاعلي.

---

## `comodor setup` — اختيار مزوّد ونموذج

```bash
comodor setup
```

ستة أسئلة، أو سبعة إن كان وكيل آخر مثبتًا وعرض الاستيراد. يعمل تلقائيًا في أول
تشغيل؛ واستخدم هذا لتغيير رأيك لاحقًا.

تذهب الإجابات إلى `~/.comodor/config.json`.

---

## `comodor import` — من OpenClaw أو Hermes

```bash
comodor import             # bring keys, model and skills across
comodor import --dry-run   # say what it would take, change nothing
comodor import --keys-only # leave the skills and the model
```

لا يُنقل شيء ولا يُستبدل أي شيء مضبوط هنا مسبقًا. راجع
[الانتقال من وكيل آخر](migrating.md).

---

## `comodor doctor` — هل كل شيء على ما يرام؟

```bash
comodor doctor
comodor doctor --fix
```

```
  ok    config file         ~/.comodor/config.json
  ok    config permissions  0o600
  ok    provider            Anthropic · claude-sonnet-5
  ok    model               claude-sonnet-5
  ok    spend limit         $2.00 per task
  ok    brain               ~/.comodor/brain.db
  ok    skills              4 loaded
  warn  version             0.8.9 installed; 0.9.0 is out
```

يصلح `--fix` ما يمكن إصلاحه — اسم مزوّد قديم، أو دليل مفقود، أو فهرس بحث معطوب.
ولا يغيّر أبدًا شيئًا لم يُبلّغ عنه أولًا.

رمز الخروج غير صفري إذا فشل أي شيء، فيصلح في فحص صحة.

---

## `comodor web` — من متصفح

```bash
comodor web                       # here, on 127.0.0.1:8765
comodor web --port 9000
comodor web --host 0.0.0.0        # reachable from elsewhere — read the warning
comodor web --no-browser          # do not open one
comodor web --token mytoken       # a fixed token instead of a fresh one
```

الدليل الكامل: [من متصفح](web.md).

---

## `comodor telegram` — من هاتفك

```bash
comodor telegram connect <token>  # a bot from @BotFather
comodor telegram pair             # a one-time code that adds your account
comodor telegram start            # here, holding this terminal
comodor telegram start -b         # detached; survives closing the terminal
comodor telegram stop             # end a background one
comodor telegram service install  # start it at login, so a reboot brings it back
comodor telegram service show     # read the unit before trusting it
comodor telegram status           # what is configured, who may talk, is it up
comodor telegram writes on        # let a phone turn edit files
comodor telegram writes off
comodor telegram forget 12345     # revoke one account
comodor telegram forget all
comodor telegram off              # stop without forgetting anything
```

يعرض إعداد أول تشغيل كل ذلك في سؤاله الأخير؛ وهذه أوامر لتغييره لاحقًا، أو لجهاز
مضبوط مسبقًا.

الدليل الكامل: [من هاتفك](telegram.md).

---

## `comodor slack` — من مساحة عمل Slack

```bash
comodor slack manifest            # the app definition to paste into Slack
comodor slack connect             # the two tokens, checked as you paste them
comodor slack pair                # a one-time code that adds your account
comodor slack start               # here, holding this terminal
comodor slack start -b            # detached
comodor slack stop
comodor slack service install     # start it at login
comodor slack status              # what is set, who may talk, is it running
comodor slack writes on           # let a Slack turn edit files
comodor slack forget U01234567
comodor slack off
```

نحو خمس دقائق، وبلا عنوان عام: يجعل Socket Mode التطبيق يفتح websocket إلى
الخارج بدل أن يُرسَل إليه.

الدليل الكامل: [من Slack](slack.md).

---

## `comodor whatsapp` — من رقم WhatsApp

```bash
comodor whatsapp connect          # guided: links each page, checks each value
comodor whatsapp connect --number-id … --token … --app-secret …
comodor whatsapp webhook          # what to paste into Meta's dashboard
comodor whatsapp pair             # a one-time code that adds your number
comodor whatsapp start            # here, holding this terminal
comodor whatsapp start --tunnel   # and bring a Cloudflare tunnel up with it
comodor whatsapp start -b         # detached
comodor whatsapp stop
comodor whatsapp service install  # start it at login
comodor whatsapp status           # what is set, who may talk, is it running
comodor whatsapp writes on        # let a phone turn edit files
comodor whatsapp forget 15551234567
comodor whatsapp off
```

تسلّم Meta الرسائل إلى عنوان URL بدل أن تدعك تستطلعها، لذا يحتاج هذا واحد إلى
عنوان HTTPS عام. ويجري `connect` دون وسائط الإعداد كله ويقيم النفق بنفسه؛ نحو
عشرين دقيقة في المرة الأولى، أكثرها في لوحة Meta. لا رقم حقيقي، لا بطاقة، لا
تحقق تجاري.

الدليل الكامل: [من WhatsApp](whatsapp.md).

---

## `comodor skills` — إجراءات يتّبعها

```bash
comodor skills browse             # what is available
comodor skills list               # what you have
comodor skills add review taste   # install some
comodor skills update             # refresh installed ones
comodor skills remove review
```

الدليل الكامل: [المهارات](skills.md).

---

## `comodor mcp` — خوادم Model Context Protocol

```bash
comodor mcp list                  # what you have, and what it offers
comodor mcp catalogue             # what is available
comodor mcp add filesystem        # from the catalogue
comodor mcp custom NAME -- CMD    # a command of your own
comodor mcp remote NAME URL       # an HTTP server
comodor mcp enable NAME
comodor mcp disable NAME
comodor mcp remove NAME
comodor mcp test NAME             # connect and list its tools
```

الدليل الكامل: [خوادم MCP](mcp.md).

---

## `comodor update` — الانتقال إلى أحدث إصدار

```bash
comodor update --check     # what is out there, change nothing
comodor update             # do it
```

يستنتج كيف ثُبّتت هذه النسخة — `uv` أو `pipx` أو `pip` أو نسخة عمل من المصدر —
ويستخدم الصحيح. وتُترك نسخة العمل من المصدر حالها: فهي ملكك.

---

## `comodor uninstall` — إزالته تمامًا

```bash
comodor uninstall --dry-run    # list what would go
comodor uninstall              # ask, then do it
comodor uninstall --yes        # for scripts
```

```
Your data
  everything it has learned and everything you told it     4.2 MB
    ~/.comodor
    settings and your API key · 812 lessons · 47 sessions · 4 skills

In your projects
  api-server                                               128 KB
    ~/projects/api-server/.comodor
    checkpoints, project settings, project skills

The program
  the uv installation
    ~/.local/share/uv/tools/comodor

4.3 MB across 3 places. None of it can be undone.
```

يسمّي كل شيء قبل أن يزيل أي شيء، ويقول ما لا يستطيع إيجاده — فمجلد `.comodor`
في مشروع استخدمته وقد مُسح سجل جلساته لا يمكن تسميته، ويخبرك بذلك بدل التظاهر.

---

## `comodor preview` — الواجهة بحجم معين

```bash
comodor preview 80x24
comodor preview 200x50 --svg wide.svg
```

يرسم إطارًا واحدًا ويخرج. مفيد لفحص طرفية ضيقة، أو لقطة شاشة.

---

## متغيرات البيئة

| | |
|---|---|
| `ANTHROPIC_API_KEY`، `OPENAI_API_KEY`، … | مفتاح، لكل مزوّد |
| `COMODOR_PROVIDER`، `COMODOR_MODEL` | فرض مزوّد أو نموذج |
| `COMODOR_HOME` | أين تسكن الإعدادات والذاكرة والجلسات |
| `COMODOR_BANNER=0` | بلا شعار كلمة في هذا التشغيل |
| `COMODOR_NO_IMPORT=1` | عدم عرض الاستيراد من وكيل آخر |
| `COMODOR_WEB_TOKEN` | رمز ثابت لواجهة الويب |
| `NO_COLOR` | بلا لون، محترم في كل مكان |

المفتاح في البيئة **لا يُكتب أبدًا إلى ملف إعدادك**. فتصديره بدل حفظه قرار،
ويحترم `/save` ذلك. راجع [الإعداد](configuration.md).

---

## رموز الخروج

| | |
|---|---|
| `0` | نجح |
| `1` | لم ينجح |
| `130` | قاطعته |

---

## انظر أيضًا

- [الواجهة](interface.md) — القوة نفسها، تفاعليًا
- [الإعداد](configuration.md) — جعل علَم دائمًا
- [استكشاف الأخطاء وإصلاحها](troubleshooting.md) — عندما لا يفعل أمر ما يقوله
