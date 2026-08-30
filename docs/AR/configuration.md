# الإعداد

ملف JSON واحد لا تضطر أبدًا إلى تحريره يدويًا — لكن هذا كل ما فيه.

---

## أين تسكن الأشياء

| | |
|---|---|
| `~/.comodor/config.json` | ملفك. يكتبه المعالج؛ أذونات مالك فقط |
| `~/.comodor/brain.db` | ما تعلمه |
| `~/.comodor/sessions/` | كل محادثة |
| `~/.comodor/skills/` | مهارات ثبّتتها أو كتبتها |
| `./.comodor/config.json` | ملف المشروع. آمن للتثبيت في المستودع — راجع [ما يجوز له أن يضبط](safety.md#what-a-repository-may-set) |
| `./.comodor/checkpoints/` | المحتويات السابقة لكل ملف غيّره |

على Windows، يكون `~/.comodor` هو `%APPDATA%\Comodor`. ويتجاوزه `COMODOR_HOME`
في كل مكان.

```bash
comodor doctor      # tells you exactly where all of these are
```

---

## أيّها يحسم

أربع طبقات. اللاحق يغلب الأسبق.

```
1. built-in defaults
2. ~/.comodor/config.json         yours
3. ./.comodor/config.json         the project's — restricted
4. environment variables          ANTHROPIC_API_KEY, COMODOR_MODEL, …
5. the command line               --model, --mode, … for one run
```

### ما يكتبه `/save`

**ما اخترته فقط.** وهذا أهم مما يبدو.

الإعداد الذي يعمل عليه الوكيل هو الطبقات الأربع كلها مدموجة. ولو أُعيدت كتابته
إلى ملفك لصار سقف الإنفاق الخاص بمستودع مستنسخ افتراضيًا دائمًا عالميًا لديك،
ولنُسخ مفتاح API احتفظت به عمدًا في بيئتك إلى القرص.

لذلك يتذكر `/save` من أين جاءت كل قيمة. فالقيمة التي لا تزال تحمل ما زوّدتها
طبقة مستعارة تعود إلى ما قاله ملفك *أنت*؛ والقيمة التي غيّرتها خلال الجلسة
تخصك وتُكتب.

- `/model x` ثم `/save` → يثبّت `x`
- `/save` في مستودع يثبّت `max_cost_usd: 500` → لا يثبّت شيئًا من هذا القبيل
- `/save` مع `ANTHROPIC_API_KEY` مُصدَّر → يبقى المفتاح في بيئتك

---

## كل إعداد

### `provider` و`model`

```json
{ "provider": "anthropic", "model": "claude-sonnet-5" }
```

راجع [اختيار نموذج](models.md).

### `agent` — كيف يعمل

```json
{
  "agent": {
    "mode": "act",
    "loop": true,
    "max_steps": 0,
    "max_seconds": 3600.0,
    "max_cost_usd": 2.0,
    "context_limit": 1000000,
    "compact_at": 0.75,
    "temperature": 0.3,
    "max_output_tokens": 8192,
    "max_tool_chars": 12000,
    "keep_screenshots": 2,
    "system_prompt_extra": "",
    "prompt_cache": true,
    "prompt_cache_ttl": "5m"
  }
}
```

| | |
|---|---|
| `mode` | `act`، `plan` (للقراءة فقط)، `chat` (بلا أدوات) |
| `loop` | مواصلة العمل حتى الانتهاء، أو الإجابة مرة واحدة |
| `max_steps` | **`0` — بلا حد، وهذا هو الافتراضي.** إعادة هيكلة عبر دزينة ملفات نفدت منه أربعٌ وعشرون خطوة في منتصف الفكر، وعدد الخطوات لا علاقة له بالضرر. اضبط رقمًا لإعادته |
| `max_seconds` | ساعة. و`0` بلا حد |
| `max_cost_usd` | السقف الذي يقابل ما تكلفه الأخطاء — [حيث يكون للنموذج سعر معلَن](cost.md#when-the-limit-cannot-fire). و`0` بلا حد |
| `context_limit` | المقياس. يتبع النموذج تلقائيًا عند التبديل |
| `compact_at` | لخّص السجل بعد تجاوز هذا الجزء من الحد |
| `max_tool_chars` | كم من مخرجات أداة واحدة يصل إلى النموذج. والباقي يُكتب في ملف يُخبر كيف يقرؤه — لا يُقتطع |
| `keep_screenshots` | كم منها يبقى في المحادثة. [السبب](computer.md#screenshots-and-what-they-cost) |
| `system_prompt_extra` | تعليماتك الدائمة أنت |
| `prompt_cache` | إتاحة إعادة تقديم البادئة غير المتغيرة من المزوّد. [التكلفة](cost.md) |
| `prompt_cache_ttl` | `5m` أو `1h`. فالساعة تكلف أكثر عند الكتابة |

### `safety` — ما يجوز له فعله

```json
{
  "safety": {
    "auto_approve_safe": true,
    "auto_approve_writes": false,
    "auto_approve_shell": false,
    "checkpoints": true,
    "workspace_only": true,
    "allow_commands": [],
    "deny_commands": ["rm -rf /", "..."],
    "max_file_read_bytes": 512000,
    "max_file_scan_bytes": 64000000,
    "trusted_folders": []
  }
}
```

الشرح الكامل: [السلامة والأذونات](safety.md).

### `learning` — ما يتذكره

```json
{
  "learning": {
    "enabled": true,
    "top_k": 6,
    "max_playbook_tokens": 800,
    "reflect": true,
    "reflect_model": "",
    "min_confidence": 0.15,
    "half_life_days": 45.0,
    "share_scope": "project",
    "associative": true,
    "corrections": true,
    "rules": true,
    "announce": true,
    "prefetch": true
  }
}
```

| | |
|---|---|
| `top_k` | الدروس المستدعاة في كل دور |
| `max_playbook_tokens` | سقف صارم لما يجوز للاستدعاء حقنه |
| `reflect` | تقطير الدروس بعد مهمة — وهذه كلّف نداء نموذج |
| `reflect_model` | نموذج أرخص لذلك، إن شئت |
| `half_life_days` | سرعة تلاشي درس غير مستخدم |
| `share_scope` | `project` أو `global` |
| `corrections`، `rules`، `announce`، `prefetch` | المسار السريع — مجاني، بلا نداء نموذج، يعمل حتى حين يكون `reflect` متوقفًا |

الشرح الكامل: [كيف يتعلم](learning.md).

### `ui` — كيف يبدو

```json
{
  "ui": {
    "theme": "ember",
    "ascii_borders": false,
    "mouse": true,
    "max_fps": 20,
    "show_timestamps": false,
    "sidebar": true,
    "banner": true,
    "syntax_theme": ""
  }
}
```

يطفئ `banner: false` شعار الكلمة نهائيًا؛ ويفعله `COMODOR_BANNER=0` لتشغيل واحد.

### `skills` — الإجراءات

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000,
    "install_examples": true
  }
}
```

الشرح الكامل: [المهارات](skills.md).

### `telegram` — من هاتفك

```json
{
  "telegram": {
    "enabled": false,
    "token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300
  }
}
```

| | |
|---|---|
| `enabled` | ما إذا كان `comodor telegram start` يشغّل البوت |
| `token` | من [@BotFather](https://t.me/botfather). يسأل عنه إعداد أول تشغيل، أو `comodor telegram connect` |
| `allowed` | معرّفات مستخدمي Telegram الرقمية التي يجيبها، ولا أحد غيرهم. يمتلئ بـ `comodor telegram pair`، ولا مرة من Telegram نفسه |
| `allow_writes` | ما إذا كان الدور الذي يبدأ من هاتف يجوز له تعديل الملفات وتشغيل الأوامر. وإيقافه يُبقيه في نمط الخطة مهما ضبطت الطرفية |
| `pair_window` | عدد الثواني التي يظل فيها رمز الاقتران صالحًا |

**لا يجوز لملف `.comodor/config.json` الخاص بمشروع أن يضبط أيًا من هذا.** فمستودع يقدر أن يضيف حسابًا إلى `allowed` سيكون بابًا خلفيًا، وعلى خلاف المتصفح أو الشاشة لا يكون لهذا أي أثر مرئي وهو يقع.

الشرح الكامل: [من هاتفك](telegram.md).

### `slack` — من مساحة عمل Slack

```json
{
  "slack": {
    "enabled": false,
    "bot_token": "",
    "app_token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300,
    "team": ""
  }
}
```

| | |
|---|---|
| `bot_token` | `xoxb-…` من OAuth & Permissions. يفعل كل ما يفعله البوت |
| `app_token` | `xapp-…` من Basic Information، بالنطاق `connections:write`. يفتح websocket الخاص بـ Socket Mode، ولا شيء غير ذلك |
| `allowed` | معرّفات مستخدمي Slack التي يجيبها. وليست أسماء العرض: يمكن لمن يملك اسم العرض أن يغيّره |
| `allow_writes` | ما إذا كان دور Slack يجوز له تعديل الملفات وتشغيل الأوامر |
| `pair_window` | عدد الثواني التي يظل فيها رمز الاقتران صالحًا |
| `team` | مساحة العمل التي اتصل بها، محفوظة كي يستطيع `status` تسميتها دون ذهاب وإياب |

**لا يجوز لملف `.comodor/config.json` الخاص بمشروع أن يضبط أيًا من هذا**، للسبب
نفسه مع الآخرين: مستودع يقدر أن يضيف حسابًا إلى `allowed` سيكون بابًا خلفيًا.

الشرح الكامل: [من Slack](slack.md).

### `whatsapp` — من رقم WhatsApp

```json
{
  "whatsapp": {
    "enabled": false,
    "token": "",
    "phone_number_id": "",
    "app_secret": "",
    "verify_token": "",
    "allowed": [],
    "allow_writes": false,
    "host": "127.0.0.1",
    "port": 8770,
    "path": "/whatsapp",
    "public_url": "",
    "api_version": "v21.0"
  }
}
```

| | |
|---|---|
| `token` | رمز وصول من Meta. رمز مستخدم النظام لا ينتهي؛ أما رمز اللوحة نفسها فيدوم 24 ساعة |
| `phone_number_id` | المعرّف الرقمي الذي تعرضه Meta بجوار الرقم، وليس الرقم |
| `app_secret` | يوقَّع به كل webhook. ودونه لا يُتحقق من شيء |
| `verify_token` | يُرَدّ صداه أثناء المصافحة الواحدة من Meta. مولَّد، لا مختار |
| `allowed` | الأرقام التي يجيبها، تقارن كأرقام. وكل غيرهم يحصل على صمت |
| `allow_writes` | ما إذا كان دور WhatsApp يجوز له تعديل الملفات وتشغيل الأوامر |
| `host`، `port`، `path` | أين يستمع الـ webhook. على المضيف المحلي، خلف ما يُنهي TLS |
| `public_url` | العنوان الذي تسلّم إليه Meta، محفوظ كي يستطيع `whatsapp webhook` طباعته |
| `api_version` | مثبَّت، لأن Meta تُقادم الإصدارات على تقويمها لا على تقويمك |

**لا يجوز لملف `.comodor/config.json` الخاص بمشروع أن يضبط أيًا من هذا**، للسبب
نفسه مع `telegram`: مستودع يقدر أن يضيف رقمًا إلى `allowed` سيكون بابًا خلفيًا
لا شيء على الشاشة يُظهر حدوثه.

الشرح الكامل: [من WhatsApp](whatsapp.md).

### `browser` — المتصفح الحقيقي

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

هكذا تشاهد `headless: false` عمله. ويلحق `port` بمتصفح شغّلته أنت، فيستطيع
استخدام جلسة سجلت دخولها إليها أصلًا بدل أن تُسلَّم إليه ملف تعريفك.

الشرح الكامل: [المتصفح الحقيقي](browser.md).

### `computer` — شاشتك

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

الشرح الكامل: [استخدام شاشتك](computer.md).

### `gateway` — التوجيه عبر المزوّدين

```json
{
  "gateway": {
    "enabled": false,
    "policy": "quality",
    "chain": [],
    "failure_threshold": 3,
    "cooldown_seconds": 60.0
  }
}
```

`policy` إما `cost` أو `speed` أو `quality`. ومع `enabled: true` يختار من
`chain` ويتجاوز مزوّدًا يواصل الفشل. وتصل إليه عبر `F5` أو `/gw` في الواجهة.

### `mcp` — خوادم Model Context Protocol

```json
{
  "mcp": {
    "enabled": true,
    "servers": { }
  }
}
```

يُدار بـ `comodor mcp`، لا يدويًا. [خوادم MCP](mcp.md).

---

## متغيرات البيئة

| | |
|---|---|
| `ANTHROPIC_API_KEY`، `OPENAI_API_KEY`، `OPENROUTER_API_KEY`، … | واحد لكل مزوّد |
| `<PROVIDER>_BASE_URL`، `<PROVIDER>_MODEL` | تجاوز نقطة نهاية أو نموذج |
| `COMODOR_PROVIDER`، `COMODOR_MODEL` | فرض أيًّا منهما |
| `COMODOR_HOME` | أين يسكن كل شيء |
| `COMODOR_BANNER=0` | بلا شعار كلمة |
| `COMODOR_NO_IMPORT=1` | عدم عرض الاستيراد من وكيل آخر |
| `COMODOR_WEB_TOKEN` | رمز ثابت لواجهة الويب |
| `NO_COLOR` | بلا لون |

---

## عندما لا يفيد إعداد ما

يقول Comodor ذلك بدل أن يتجاهلك:

```
config: agent.max_steps must be a whole number; keeping 24
config: this project cannot set safety, computer — only your own can
```

تُحوَّل قيمة النوع الخاطئ حيث يكون ذلك بلا لبس، وتُرفض حيث ليس كذلك، ويسمّي
الرفض المفتاح وما كان متوقعًا. و`null` لا يستبدل بصمت سلسلة بـ `None`.

إن بدا إعداد ما وكأنه لا يفعل شيئًا:

```bash
comodor doctor          # what it actually loaded
```

```
/settings               # the same, in the interface
```
