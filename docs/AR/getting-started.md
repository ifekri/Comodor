# البداية

خمس دقائق، تنتهي بالوكيل وهو يؤدي شيئًا مفيدًا.

---

## 1. التثبيت

سطر واحد. ويتولى هو الباقي.

**macOS · Linux · BSD**

```bash
curl -fsSL get.comodor.ai | sh
```

**Windows** — PowerShell

```powershell
irm get.comodor.ai | iex
```

```
Comodor — it learns the way you correct it.

  Linux x86_64
> Installing uv, a package manager Comodor needs (about 15 MB)
  from https://astral.sh/uv — it fetches a Python too, if one is missing
> Installing with uv

✓ comodor 0.9.0

  Linked into /usr/local/bin, which is on your PATH.

  comodor              start the interface
  comodor --demo       try it offline, no API key needed
  comodor doctor       check what is configured
```

**عنوان واحد لكليهما.** لا يسمّي `get.comodor.ai` أي ملف. إنه يقرأ أي عميل
يسأل ويرسل `curl` و`wget` إلى مثبّت الصدفة، وPowerShell إلى مثبّت Windows،
والمتصفح إلى هذه الصفحة — بحيث يكون السطر الذي تلصقه هو السطر نفسه على كل
نظام، ولا تضطر أبدًا إلى الاختيار.

**يُطب إلى النهاية.** من يشغّل سطرًا واحدًا من صفحة ويب لم يوافق على تنقيح أي
شيء، لذا يثبّت السكربت ما يحتاجه — بيئة معزولة، ومدير حزم، وPython — بدلًا
من التوقف لشرح ما كان يفترض أن يكون لديك مسبقًا. جرّب وأُثبت على
`debian:bookworm-slim` نقية خالية من Python تمامًا.

### لا شيء تقريبًا تكتبه بعدها

حيثما يستطيع، يضع `comodor` في مكان تبحث فيه صدفتك أصلًا، فيعمل في الطرفية
التي شغّلته منها — دون `export` ودون نافذة جديدة. يغطي ذلك root والحاويات
وCI وأي جهاز Mac يحتوي Homebrew.

وحيثما لا يستطيع — حساب Linux عادي لا شيء فيه على `PATH` قابل للكتابة —
لا يستطيع أي مثبّت تقديم المساعدة، لأن عملية ابنًا لا يمكنها تغيير بيئة
الصدفة التي شغّلتها. لذا يقول ذلك:

```
  Every new terminal can run comodor already.
  This one started before the install, and no installer
  can reach back into the shell that ran it. For this
  terminal only:

    export PATH="/home/you/.local/bin:$PATH"
```

افتح طرفية جديدة ويعمل ببساطة. يُدرج السطر في كل من ملف rc الخاص بصدفتك
وملف تعريف تسجيل دخولك، فتجده كل أنواع الصدفات — التفاعلية، وتسجيل
الدخول، وغير التفاعلية، وجلسة سطح المكتب.

### إن كنت تفضّل عدم تمرير سكربت إلى الصدفة عبر أنبوب

أمر معقول تمامًا. كلا السكربتين نص عادي يمكنك قراءته أولًا — ومسمايَان
بمباشرة، لأن العنوان القصير يرسل أي شيء ليس أداة جلب إلى الصفحة:

```bash
curl -fsSL https://comodor.ai/install.sh  | less
curl -fsSL https://comodor.ai/install.ps1 | less
```

أو استخدم مدير حزم تملكه أصلًا:

```bash
uv tool install comodor      # isolated, and the fastest
pipx install comodor         # isolated
pip install comodor          # into whatever environment you are in
```

يحتاج Comodor إلى **Python 3.11 أو أحدث** ولا شيء غير ذلك.

### تحقق من وصوله

```bash
comodor --version
```

إذا لم تجدها الصدفة، فقد أضاف المثبّت دليلًا إلى `PATH` لا تعرفه هذه الطرفية
بعد. افتح طرفية جديدة، أو شغّل سطر `export` الذي طبعته المثبّت.

### خيارات يفهمها المثبّتون

| | |
|---|---|
| `COMODOR_FORCE_TOOL` | ثبّت الطريقة: `uv` أو `pipx` أو `venv` أو `pip` |
| `COMODOR_NO_BOOTSTRAP` | لا تنزّل أداة أبدًا؛ افشل بدلًا من ذلك |
| `COMODOR_NO_MODIFY_PATH` | لا تمسّ ملف تعريف صدفتك |
| `COMODOR_INSTALL_REF` | ثبّت من مرجع git أو من مسار محلي بدلًا من PyPI |

```bash
COMODOR_NO_MODIFY_PATH=1 curl -fsSL get.comodor.ai | sh
```

> **لست متأكدًا بعد أنك تريد تثبيته؟** يشغّل `comodor --demo` الواجهة كاملة
> أمام مزوّد دون اتصال مخطط له مسبقًا. لا مفتاح، لا حساب، لا شبكة.

---

## 2. اختر نموذجًا

شغّله. في المرة الأولى يطرح ستة أسئلة ولا يسأل مجددًا أبدًا.

```bash
comodor
```

```
 1/6  Which model provider?
┌─  Providers  ───────────────────────────────────────────┐
│ ›  OpenRouter        One key, hundreds of models         │
│    Anthropic         Claude, direct from the source      │
│    OpenAI            GPT models, direct                  │
│    Ollama (local)    Runs on your machine. No key        │
└──────────────────────────────────────────────────────────┘
  ↑↓ move   enter choose   tab more   esc cancel
```

مفاتيح الأسهم، أو اكتب للتصفية. يفتح **Tab** الوصف الكامل لما يشير إليه
السهم، في الإطار نفسه — تعرض القوائم سطرًا واحدًا لكل صف كي تتسع للشاشة،
وبعض تلك الأوصاف فقرة كاملة.

عند التمرير عبر أنبوب أو عند التشغيل المخطط، تصل الأسئلة نفسها في صورة
قائمة مرقّمة، بحيث يمكن أتمتتها.

**لا مفتاح ولا مال؟** اختر **Ollama** أو **LM Studio**. تعملان على جهازك،
ولا تحتاجان مفتاحًا، ولا تكلفان شيئًا. كل شيء في هذا التوثيق يعمل معهما ما
عدا الأجزاء التي تنص على غير ذلك.

**تستخدم OpenClaw أو Hermes أصلًا؟** تعرض الشاشة الأولى إحضار مفاتيحك
ونموذجك ومهاراتك إليه. لا يُنقل شيء ولا يُستبدل أي شيء مضبوط هنا مسبقًا.
راجع [الانتقال من وكيل آخر](migrating.md).

تُحفظ إجاباتك في `~/.comodor/config.json`، لا يقرؤه سواك. غيّر رأيك لاحقًا
عبر `comodor setup`، أو إعدادًا واحدًا في كل مرة — راجع
[الإعداد](configuration.md).

### السؤال الأخير هو هاتفك

```
 6/6  Run it from your phone?
┌─  From your phone  ─────────────────────────────────────────────┐
│ ›  Not now    you can set any of them up later                   │
│    Telegram   one token from @BotFather — about a minute         │
│    Slack      an app from a manifest, two tokens — five minutes  │
│    WhatsApp   a Meta app and a public address — twenty minutes   │
└──────────────────────────────────────────────────────────────────┘
```

يأخذ **Telegram** رمزًا مميزًا من [@BotFather](https://t.me/botfather)،
ويتحقق منه لدى Telegram هناك وفورًا، ويعرض رمزًا ترسله للبوت كي يعرف أي حساب
يجيب — دقيقة واحدة من البداية إلى النهاية.
راجع [من هاتفك](telegram.md).

يستغرق **Slack** نحو خمس دقائق. يُنشأ التطبيق من ملف manifest يطبعه Comodor،
فهو لصقة واحدة لا صفحة من خانات الاختيار، ويعني Socket Mode عدم وجود عنوان
عام إطلاقًا — راجع [من Slack](slack.md).

يفعل **WhatsApp** الشيء نفسه ويستغرق نحو عشرين دقيقة: تطبيق Meta، ورقم عمل،
وسر تطبيق، وعنوان HTTPS عام، ولا يمكن صنع أي منها من طرفية. يستحق العناء
فقط إذا كان لا بد أن يكون WhatsApp — راجع
[من WhatsApp](whatsapp.md).

في كلتا الحالتين يقرأ ويخطط فقط حتى تقول غير ذلك، ورفض ذلك يكلّف ضغطة
مفتاح واحدة.

### ثم يعرض البدء

```
 What now?
   1  Start Comodor          — the interface, here in this terminal
   2  Start the Telegram bot — in the background, answers while this is closed
   3  Both
   4  Nothing yet            — `comodor` starts it whenever you want
```

كان الإعداد قديمًا ينتهي هنا، مع العودة إلى موجه الصدفة دون أي شيء يعمل.
ويظهر سطر هاتف لكل قناة متصلة ومقترنة، ومسمّى — فمن أعد WhatsApp لا يُعرض
عليه «بوت Telegram».

---

## 3. يسألك عن المجلد

```
  Work in  /home/you/projects/api-server ?
```

يُسأل مرة واحدة لكل مجلد. كل ما يجوز للوكيل لمسه يقع تحته — لا يستطيع القراءة
أو الكتابة خارجه إلا إذا عطّلت ذلك عن قصد. تُتذكَّر المجلدات الموافق عليها.

---

## 4. اطلب شيئًا

اكتبه واضغط Enter.

```
> the tests in tests/test_parser.py are failing, work out why and fix it
```

سيقرأ الملفات، ويشغّل الاختبارات، ويغيّر شيئًا. وقبل أن يكتب ملفًا تحصل على
فرق diff وخيار:

```
  Write  src/parser.py
    - 12 lines removed, 8 added
  [a] allow   [A] allow always this session   [d] deny
```

أجب بـ `a` مرة واحدة، أو `A` إذا فضّلت ألا يستمر في السؤال بقية الجلسة. كل
كتابة محفوظة كنقطة استرجاع في الحالتين: يعيد `/undo` آخر واحدة.

---

## 5. صحّحه — وهذا هو الجزء المهم

عندما يخطئ في شيء، أخبره. طريقتان، وكلتاهما تعلّمه الشيء نفسه:

**عدّل الملف بنفسك.** يلاحظ Comodor ما غيّرته في مخرجاته.

**قل ذلك.**

```
> no — we use single quotes in this codebase, not double
```

في كلتا الحالتين يصبح درسًا: يُستدعى في المرة القادمة عندما يبدو الوضع
مشابهًا، بدرجة ثقة ترتفع عندما يثبت صحه وتتراجع عندما لا يثبت.

بعد بضع جلسات:

```
> /progress
```

```
◈ Corrections per task down 100% since the first tasks in this project.

metric                trend                       now  vs first
Steps per task        ▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇    6.1      ↑10%
Corrections per task  ████████▅▅▅▅▅▅▅▅▁▁▁▁▁▁▁▁    0.0     ↓100%
Approvals asked       ▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅    2.0         —
Tokens per task       ▁▁▁▂▂▂▃▃▃▄▄▄▅▅▅▆▆▆▇▇▇███  12.0K      ↑40%
First-try success     ▁██████▁██████▁██████▁██    86%         —

brain    7 rules · 812 lessons · 24 corrections learned from
history  24 tasks over 8 days
success  83% overall
```

هذا دليل، لا دعوى. إذا كان معدل التصحيح لا يتناقص، فالتعلم لا يعمل، وتقول
اللوحة ذلك بدلًا من إخفائه.

يشرح [كيف يتعلم](learning.md) الآلية.

---

## 6. الأشياء التي يستحق معرفتها في اليوم الأول

```
/help          every command
/mode          act · plan (read-only) · chat (no tools)     F3 cycles
/undo          restore the last file it changed
/cost          tokens, spend, what the cache saved
Esc            stop it, mid-thought
Ctrl-C twice   leave
```

---

## إلى أين تتجه بعد ذلك

| تريد أن | اقرأ |
|---|---|
| تستخدمه دون الواجهة، في سكربت | [من الطرفية](cli.md) |
| تعرف بدقة ما يستطيع فعله بجهازك | [السلامة والأذونات](safety.md) |
| تدفع أقل | [التكلفة](cost.md) |
| تتيح له استخدام متصفح | [المتصفح الحقيقي](browser.md) |
| تتيح له استخدام الفأرة ولوحة المفاتيح | [استخدام شاشتك](computer.md) |
| تكتب إجراءً يتّبعه في كل مرة | [المهارات](skills.md) |
| تشغّله على خادم، أو في Docker | [من متصفح](web.md)، [في Docker](docker.md) |

---

## إذا حدث خطأ ما

```bash
comodor doctor
```

يفحص كل ما يستطيع ويخبرك بما تفعله تجاه أي شيء يعثر عليه. يصلح
`comodor doctor --fix` ما يمكن إصلاحه. راجع
[استكشاف الأخطاء وإصلاحها](troubleshooting.md).
