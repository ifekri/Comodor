# پیکربندی

یک فایل JSON که هرگز مجبور به ویرایش دستی‌اش نیستید — ولی اینجا هر چیزی که
درونش هست آمده.

---

## چه چیزهایی کجا زندگی می‌کنند

| | |
|---|---|
| `~/.comodor/config.json` | مال شما. جادوگرش را می‌نویسد؛ مجوزهای فقط‌مالک |
| `~/.comodor/brain.db` | آنچه یاد گرفته |
| `~/.comodor/sessions/` | تک‌تک گفت‌وگوها |
| `~/.comodor/skills/` | مهارت‌هایی که نصب کرده‌اید یا نوشته‌اید |
| `./.comodor/config.json` | مال پروژه. کامیت کردنش امن است — به [چه چیزی مجاز است تنظیم کند](safety.md#what-a-repository-may-set) نگاه کنید |
| `./.comodor/checkpoints/` | محتوای قبلی تک‌تک فایل‌هایی که عوض کرده |

در ویندوز، `~/.comodor` همان `%APPDATA%\Comodor` است. `COMODOR_HOME` در همه‌جا
آن را بازنویسی می‌کند.

```bash
comodor doctor      # دقیقاً می‌گوید همهٔ این‌ها کجا هستند
```

---

## چه چیزی برنده می‌شود

چهار لایه. دیرتر بر زودتر می‌چربد.

```
1. built-in defaults
2. ~/.comodor/config.json         yours
3. ./.comodor/config.json         the project's — restricted
4. environment variables          ANTHROPIC_API_KEY, COMODOR_MODEL, …
5. the command line               --model, --mode, … for one run
```

### `/save` چه چیزی می‌نویسد

**فقط همان چیزی که شما انتخاب کرده‌اید.** این از چیزی که به نظر می‌رسد مهم‌تر
است.

پیکربندی‌ای که عامل رویش اجرا می‌شود، همهٔ چهار لایه با هم ادغام‌شده است.
نوشتن دوبارهٔ آن در فایل شما باعث می‌شد سقف هزینهٔ یک مخزن شبیه‌سازی‌شده، پیش‌فرض
دائمی و سراسری شما شود، و کلید API ای را که آگاهانه در محیط نگه داشته بودید روی
دیسک کپی کند.

پس `/save` به خاطر می‌سپارد هر مقدار از کجا آمده. مقداری که هنوز هر چه یک لایهٔ
قرضی فراهم کرده بود را نگه می‌دارد، به همان چیزی برمی‌گردد که فایلِ *خودتان*
گفته بود؛ مقداری که در طول نشست تغییر داده‌اید مال شماست و نوشته می‌شود.

- `/model x` بعد `/save` → ماندگار می‌شود `x`
- `/save` در مخزنی که `max_cost_usd: 500` را ثابت کرده → هیچ چیز از این دست
  ماندگار نمی‌شود
- `/save` با `ANTHROPIC_API_KEY` ای که export شده → کلید در محیط شما می‌ماند

---

## تک‌تک تنظیمات

### `provider` و `model`

```json
{ "provider": "anthropic", "model": "claude-sonnet-5" }
```

به [انتخاب یک مدل](models.md) نگاه کنید.

### `agent` — چطور کار می‌کند

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
| `mode` | `act`، `plan` (فقط‌خواندنی)، `chat` (بدون ابزار) |
| `loop` | کار کردن تا تمام شدن، یا یک بار پاسخ دادن |
| `max_steps` | **`0` — بی‌نهایت، و همان پیش‌فرض است.** یک refactor روی دوازده فایل وسط فکر از بیست‌وچهار گام جا کم می‌آورد، و شمار گام هیچ ربطی به آسیب ندارد. یک عدد بگذارید تا برگردد |
| `max_seconds` | یک ساعت. `0` یعنی بی‌نهایت |
| `max_cost_usd` | سقفی که به هزینهٔ خراب شدن ترجمه می‌شود — [جایی که مدل نرخ منتشرشده دارد](cost.md#when-the-limit-cannot-fire). `0` یعنی بی‌نهایت |
| `context_limit` | همان عقربه. موقع تغییر مدل خودکار دنبالش می‌رود |
| `compact_at` | تاریخچهٔ گفت‌وگو را وقتی از این کسری از سقف گذشت خلاصه کن |
| `max_tool_chars` | چه مقدار از نتیجهٔ یک ابزار به مدل برسد. بقیه در فایلی نوشته می‌شود و به آن گفته می‌شود چطور بخواندش — نه بریده شدن |
| `keep_screenshots` | چندتا در گفت‌وگو بمانند. [چرا](computer.md#screenshots-and-what-they-cost) |
| `system_prompt_extra` | دستورهای همیشگی خودتان |
| `prompt_cache` | اجازه بده ارائه‌دهنده پیشوند تغییرناپذیر را دوباره سرو کند. [هزینه](cost.md) |
| `prompt_cache_ttl` | `5m` یا `1h`. آن ساعت، نوشتنش گران‌تر تمام می‌شود |

### `safety` — چه اجازه‌ای دارد بکند

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

توضیح کامل: [ایمنی و مجوزها](safety.md).

### `learning` — چه چیزی را به خاطر می‌سپارد

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
| `top_k` | چند درس در هر نوبت به یاد می‌آورد |
| `max_playbook_tokens` | سقف سخت روی آنچه recall اجازه دارد تزریق کند |
| `reflect` | بعد از یک وظیفه درس‌ها را تقطیر کن — این یکی یک فراخوان مدل هزینه دارد |
| `reflect_model` | یک مدل ارزان‌تر برای همین، اگر خواستید |
| `half_life_days` | یک درس بلااستفاده چقدر سریع محو می‌شود |
| `share_scope` | `project` یا `global` |
| `corrections`، `rules`، `announce`، `prefetch` | خط سریع — رایگان، بدون فراخوان مدل، حتی وقتی `reflect` خاموش است روشن |

توضیح کامل: [نحوهٔ یادگیری آن](learning.md).

### `ui` — چطور دیده می‌شود

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

`banner: false` وردمارک را برای همیشه خاموش می‌کند؛ `COMODOR_BANNER=0` فقط
یک اجرا.

### `skills` — رویه‌ها

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

توضیح کامل: [مهارت‌ها](skills.md).

### `telegram` — از گوشی شما

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
| `enabled` | آیا `comodor telegram start` ربات را اجرا کند |
| `token` | از [@BotFather](https://t.me/botfather). راه‌اندازی اولین اجرا می‌پرسد، یا `comodor telegram connect` |
| `allowed` | شناسه‌های عددی کاربران تلگرامی که به آن‌ها جواب می‌دهد، و هیچ‌کس دیگر. با `comodor telegram pair` پر می‌شود، هرگز از خود تلگرام نه |
| `allow_writes` | آیا نوبتی که از گوشی شروع شده اجازه دارد فایل‌ها را ویرایش کند و فرمان اجرا کند. خاموش، در حالت plan نگهش می‌دارد با هر تنظیمی که ترمینال داشته باشد |
| `pair_window` | چند ثانیه یک کد جفت‌سازی معتبر می‌ماند |

**پیکربندی پروژه حق تنظیم هیچ‌کدام از این‌ها را ندارد.** مخزنی که بتواند حسابی
به `allowed` اضافه کند یک در پشتی است، و برخلاف مرورگر یا صفحه، هیچ چیز قابل
مشاهده‌ای در حین رخ دادن وجود نداشت.

توضیح کامل: [از گوشی شما](telegram.md).

### `slack` — از یک فضای کاری Slack

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
| `bot_token` | `xoxb-…` از OAuth & Permissions. هر کاری که ربات می‌کند را انجام می‌دهد |
| `app_token` | `xapp-…` از Basic Information، دامنهٔ `connections:write`. وب‌سوکت Socket Mode را باز می‌کند، و هیچ چیز دیگری |
| `allowed` | شناسه‌های کاربر Slack ای که به آن‌ها جواب می‌دهد. نه نام نمایشی: نام نمایشی را می‌توان از طرف خودش عوض کرد |
| `allow_writes` | آیا یک نوبت Slack اجازه دارد فایل‌ها را ویرایش کند و فرمان اجرا کند |
| `pair_window` | چند ثانیه یک کد جفت‌سازی معتبر می‌ماند |
| `team` | فضای کاری‌ای که به آن وصل شده، به خاطر سپرده شده تا `status` بتواند بدون یک رفت‌وبرگشت نامش را بگوید |

**پیکربندی پروژه حق تنظیم هیچ‌کدام از این‌ها را ندارد**، به همان دلیل بقیه:
مخزنی که بتواند حسابی به `allowed` اضافه کند یک در پشتی است.

توضیح کامل: [از Slack](slack.md).

### `whatsapp` — از یک شمارهٔ WhatsApp

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
| `token` | یک توکن دسترسی متا. توکن System User منقضی نمی‌شود؛ توکن خود داشبورد ۲۴ ساعت می‌ماند |
| `phone_number_id` | شناسهٔ عددی که متا کنار شماره نشان می‌دهد، نه خود شماره |
| `app_secret` | تک‌تک وب‌هوک‌ها با آن امضا می‌شوند. بدون آن، هیچ چیز راستی‌آزمایی نمی‌شود |
| `verify_token` | در همان دست‌دادن یک‌بارِ متا پس فرستاده می‌شود. ساخته می‌شود، انتخابی نیست |
| `allowed` | شماره‌هایی که به آن‌ها جواب می‌دهد، به صورت رقم‌به‌رقم مقایسه می‌شوند. بقیه سکوت می‌گیرند |
| `allow_writes` | آیا یک نوبت WhatsApp اجازه دارد فایل‌ها را ویرایش کند و فرمان اجرا کند |
| `host`، `port`، `path` | وب‌هوک کجا گوش بدهد. لوکال‌هاست، پشت چیزی که TLS را خاتمه می‌دهد |
| `public_url` | آدرسی که متا به آن تحویل می‌دهد، به خاطر سپرده شده تا `whatsapp webhook` بتواند چاپش کند |
| `api_version` | ثابت شده، چون متا نسخه‌ها را بر اساس تقویم خودش منسوخ می‌کند نه تقویم شما |

**پیکربندی پروژه حق تنظیم هیچ‌کدام از این‌ها را ندارد**، به همان دلیل `telegram`:
مخزنی که بتواند شماره‌ای به `allowed` اضافه کند، در پشتی‌ای است که هیچ چیز روی
صفحه‌ای نشانت نمی‌دهد که دارد اتفاق می‌افتد.

توضیح کامل: [از WhatsApp](whatsapp.md).

### `browser` — مرورگر واقعی

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

`headless: false` همان چیزی است که با آن تماشایش می‌کنید کار می‌کند. `port` به
مرورگری که خودتان راه انداخته‌اید وصل می‌شود، پس می‌تواند از نشستی استفاده کند
که از قبل داخلش لاگین هستید، به جای اینکه پروفایل شما به آن داده شود.

توضیح کامل: [مرورگر واقعی](browser.md).

### `computer` — صفحهٔ شما

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

توضیح کامل: [استفاده از صفحهٔ شما](computer.md).

### `gateway` — مسیریابی میان ارائه‌دهنده‌ها

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

`policy` یکی از `cost`، `speed` یا `quality` است. با `enabled: true` از میان
`chain` انتخاب می‌کند و از ارائه‌دهنده‌ای که مدام شکست می‌خورد رد می‌شود. `F5`
یا `/gw` در رابط.

### `mcp` — سرورهای Model Context Protocol

```json
{
  "mcp": {
    "enabled": true,
    "servers": { }
  }
}
```

با `comodor mcp` مدیریت می‌شود، نه با دست. [سرورهای MCP](mcp.md).

---

## متغیرهای محیطی

| | |
|---|---|
| `ANTHROPIC_API_KEY`، `OPENAI_API_KEY`، `OPENROUTER_API_KEY`، … | یکی برای هر ارائه‌دهنده |
| `<PROVIDER>_BASE_URL`، `<PROVIDER>_MODEL` | بازنویسی یک endpoint یا مدل |
| `COMODOR_PROVIDER`، `COMODOR_MODEL` | هر کدام را تحمیل کن |
| `COMODOR_HOME` | همه‌چیز کجا زندگی می‌کند |
| `COMODOR_BANNER=0` | بدون وردمارک |
| `COMODOR_NO_IMPORT=1` | پیشنهاد وارد کردن از عامل دیگر نده |
| `COMODOR_WEB_TOKEN` | یک توکن ثابت برای رابط تحت وب |
| `NO_COLOR` | بدون رنگ |

---

## وقتی یک تنظیم اثر نمی‌کند

کامودور به جای نادیده گرفتن شما همین را می‌گوید:

```
config: agent.max_steps must be a whole number; keeping 24
config: this project cannot set safety, computer — only your own can
```

مقداری از نوع غلط هر جا که این کار بدون ابهام ممکن باشد تبدیل می‌شود، و هر جا
که نیست رد می‌شود — و رد شدن، کلید را و آنچه انتظار می‌رفت نام می‌برد. `null`
آرام و بی‌سروصدا یک رشته را با `None` جایگزین نمی‌کند.

اگر یک تنظیم هنوز انگار هیچ کاری نمی‌کند:

```bash
comodor doctor          # آنچه واقعاً بارگذاری شده
```

```
/settings               # همان، در رابط
```
