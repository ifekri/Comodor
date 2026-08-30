# از ترمینال

تک‌تک فرمان‌ها و پرچم‌ها، با چیزی که می‌توانید بچسبانید.

```bash
comodor help              # صفحهٔ راهنمای مکتوب
comodor help computer     # یک موضوع با جزئیات بیشتر
```

---

## نصب و به‌روزرسانی

```bash
curl -fsSL get.comodor.ai | sh     # macOS, Linux, BSD
```

```powershell
irm get.comodor.ai | iex          # Windows
```

`get.comodor.ai` نام فایلی را نمی‌آورد: می‌خواند کدام کلاینت در حال پرسیدن است
و با نصب‌کننده‌ای پاسخ می‌دهد که آن کلاینت بتواند اجرایش کند. همان یک خط، نصب
موجود را هم به‌روز می‌کند. یا، وقتی روی دستگاهتان است:

```bash
comodor update --check    # چه چیزی آن بیرون هست
comodor update            # برو سمتش
```

بقیهٔ ماجرا در [شروع به کار](getting-started.md#1-install) است — مدیریت‌های
بسته، و اینکه نصب‌کننده‌ها چه می‌پذیرند.

---

## راه‌اندازی

```bash
comodor                              # رابط کاربری
comodor --demo                       # رابط کاربری، آفلاین، بدون نیاز به کلید
comodor --resume                     # باز کردن دوبارهٔ آخرین نشست
comodor --resume 2026-08-22-a4f1     # باز کردن یکی با id مشخص
comodor --cwd ~/projects/api         # کار در جای دیگری جز اینجا
comodor --model claude-sonnet-5      # یک مدل دیگر، فقط برای همین اجرا
comodor --mode plan                  # شروع در حالت فقط‌خواندنی
```

### گزینه‌ها

| | |
|---|---|
| `--provider NAME` | `openrouter`، `anthropic`، `openai`، `ollama`، … |
| `--model ID` | نادیده گرفتن مدل برای همین اجرا |
| `--mode act\|plan\|chat` | plan فقط‌خواندنی است؛ chat هیچ ابزاری ندارد |
| `--no-loop` | یک بار پاسخ بده به جای کار کردن تا تمام شدن |
| `--cwd PATH` | پوشه‌ای که اجازه دارد دست بزند |
| `--theme NAME` | `ember`، `midnight`، `matrix`، `mono` |
| `--ascii` | حاشیه‌های ASCII |
| `--no-mouse` | موس را رها کن و به ترمینال بده |
| `--resume [ID]` | آخرین نشست، یا یکی با id |
| `--demo` | ارائه‌دهندهٔ آفلاینِ اسکریپت‌شده |
| `--version` | این چه نسخه‌ای است |
| `-h`، `--help` | صفحهٔ راهنمای مکتوب |

هیچ‌کدام از این‌ها در پیکربندی شما نوشته نمی‌شوند. فقط روی همان یک اجرا اثر
دارند. برای ماندگاری یک تغییر، داخل رابط از `/save` استفاده کنید یا فایل
پیکربندی را ویرایش کنید — [پیکربندی](configuration.md).

---

## `comodor run` — یک وظیفه، بدون رابط

```bash
comodor run "fix the failing test in tests/test_parser.py"
comodor run "add type hints to src/parser.py" --yes
comodor run "what does this project do?" --json
comodor run "refactor the parser" --max-steps 40
```

| | |
|---|---|
| `--yes` | تأیید خودکار نوشتن‌ها و فرمان‌ها |
| `--json` | یک نتیجهٔ قابل‌خواندن برای ماشین روی stdout |
| `--max-steps N` | نادیده گرفتن سقف گام‌ها برای همین اجرا |

بدون `--yes` می‌پرسد، روی stderr، و اگر هیچ‌چیز نتواند پاسخ بدهد به جای حدس
زدن رد می‌کند. این عمدی است: اسکریپتی که بی‌صدا خودش خودش را تأیید می‌کند،
اسکریپتی است که ساعت سه بامداد کاری می‌کند که انتظارش را نداشته‌اید.

`--json` این را به شما می‌دهد:

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

`stopped` می‌گوید چرا تمام شد — یکی از این‌ها:

| | |
|---|---|
| `done` | خودش تصمیم گرفت کار تمام است |
| `max_steps` | به `agent.max_steps` خورد |
| `budget` | به `agent.max_cost_usd` یا `agent.max_seconds` خورد |
| `cancelled` | شما قطعش کردید |
| `error` | چیزی خراب شد؛ `error` می‌گوید چه |

`ok` برای `done` و `max_steps` درست است — تمام شدن گام‌ها یک شکست نیست، بلکه
سقفی است که کارش را می‌کند — پس اگر فرقشان برایتان مهم است، `stopped` را هم
بررسی کنید:

```bash
comodor run "update the changelog for this release" --yes --json > result.json
jq -e '.stopped == "done"' result.json
```

از یک اجرای headless هم یاد می‌گیرد. اصلاحی که بعداً انجام می‌دهید، همان درسی
را می‌دهد که یک اجرای تعاملی می‌داد.

---

## `comodor setup` — انتخاب ارائه‌دهنده و مدل

```bash
comodor setup
```

شش پرسش، یا هفت تا اگر عامل دیگری نصب باشد و پیشنهاد وارد کردن بدهد. در اولین
اجرای خودکار رانده می‌شود؛ از این استفاده کنید تا بعداً نظرتان را عوض کنید.

پاسخ‌ها به `~/.comodor/config.json` می‌روند.

---

## `comodor import` — از OpenClaw یا Hermes

```bash
comodor import             # آوردن کلیدها، مدل و مهارت‌ها
comodor import --dry-run   # بگو چه می‌خواهی برداری، هیچ چیز را عوض نکن
comodor import --keys-only # مهارت‌ها و مدل را رها کن
```

هیچ چیزی جابه‌جا نمی‌شود و هیچ تنظیمی که از قبل اینجا برقرار است جایگزین
نمی‌شود. به [آمده از عامل دیگری](migrating.md) نگاه کنید.

---

## `comodor doctor` — همه‌چیز سر جایش است؟

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

`--fix` هر چه قابل تعمیر است را تعمیر می‌کند — یک نام ارائه‌دهندهٔ از رده
خارج، یک پوشهٔ غایب، یک فهرست جست‌وجوی خراب. هرگز چیزی را که اول گزارش نکرده
باشد عوض نمی‌کند.

کد خروج در صورت شکست هر چیزی غیر صفر است، پس در یک بررسی سلامت کار می‌کند.

---

## `comodor web` — از یک مرورگر

```bash
comodor web                       # همینجا، روی 127.0.0.1:8765
comodor web --port 9000
comodor web --host 0.0.0.0        # از جای دیگر قابل دسترس — هشدار را بخوانید
comodor web --no-browser          # مرورگری باز نکن
comodor web --token mytoken       # یک توکن ثابت به جای یک توکن تازه
```

راهنمای کامل: [از یک مرورگر](web.md).

---

## `comodor telegram` — از گوشی شما

```bash
comodor telegram connect <token>  # یک ربات از @BotFather
comodor telegram pair             # یک کد یک‌بار مصرف که حساب شما را اضافه می‌کند
comodor telegram start            # همینجا، نگه داشتن همین ترمینال
comodor telegram start -b         # جدا شده؛ با بستن ترمینال از بین نمی‌رود
comodor telegram stop             # پایان دادن به یکی در پس‌زمینه
comodor telegram service install  # در زمان ورود به سیستم اجرا شود، تا ریبوت هم برگرداند
comodor telegram service show     # قبل از اعتماد، واحد را بخوانید
comodor telegram status           # چه پیکربندی شده، چه کسی حق حرف دارد، آیا بالا است
comodor telegram writes on        # اجازه بده یک نوبتِ گوشی فایل‌ها را ویرایش کند
comodor telegram writes off
comodor telegram forget 12345     # لغو یک حساب
comodor telegram forget all
comodor telegram off              # توقف بدون فراموش کردن هیچ چیزی
```

نصب و راه‌اندازی اولین اجرا همهٔ این‌ها را به عنوان آخرین پرسش پیشنهاد می‌دهد؛
این‌ها برای تغییر دادنش بعداً هستند، یا برای دستگاهی که از قبل راه انداخته‌اید.

راهنمای کامل: [از گوشی شما](telegram.md).

---

## `comodor slack` — از یک فضای کاری Slack

```bash
comodor slack manifest            # تعریف اپ برای چسباندن در Slack
comodor slack connect             # دو توکن، با بررسی همان لحظهٔ چسباندن
comodor slack pair                # یک کد یک‌بار مصرف که حساب شما را اضافه می‌کند
comodor slack start               # همینجا، نگه داشتن همین ترمینال
comodor slack start -b            # جدا شده
comodor slack stop
comodor slack service install     # در زمان ورود به سیستم اجرا شود
comodor slack status              # چه تنظیم شده، چه کسی حق حرف دارد، آیا در حال اجراست
comodor slack writes on           # اجازه بده یک نوبتِ Slack فایل‌ها را ویرایش کند
comodor slack forget U01234567
comodor slack off
```

حدود پنج دقیقه، و بدون آدرس عمومی: Socket Mode باعث می‌شود اپ به بیرون یک
وب‌سوکت باز کند، نه اینکه به سمتش چیزی پست شود.

راهنمای کامل: [از Slack](slack.md).

---

## `comodor whatsapp` — از یک شمارهٔ WhatsApp

```bash
comodor whatsapp connect          # هدایت‌شده: هر صفحه را پیوند می‌دهد، هر مقدار را بررسی می‌کند
comodor whatsapp connect --number-id … --token … --app-secret …
comodor whatsapp webhook          # چه چیزی در داشبورد متا بچسبانید
comodor whatsapp pair             # یک کد یک‌بار مصرف که شمارهٔ شما را اضافه می‌کند
comodor whatsapp start            # همینجا، نگه داشتن همین ترمینال
comodor whatsapp start --tunnel   # و بالا آوردن یک تونل Cloudflare همراهش
comodor whatsapp start -b         # جدا شده
comodor whatsapp stop
comodor whatsapp service install  # در زمان ورود به سیستم اجرا شود
comodor whatsapp status           # چه تنظیم شده، چه کسی حق حرف دارد، آیا در حال اجراست
comodor whatsapp writes on        # اجازه بده یک نوبتِ گوشی فایل‌ها را ویرایش کند
comodor whatsapp forget 15551234567
comodor whatsapp off
```

متا پیام‌ها را به یک URL تحویل می‌دهد، نه اینکه اجازه بدهد برایشان poll کنید،
پس این یکی به یک آدرس HTTPS عمومی نیاز دارد. `connect` بدون آرگومان، کل
راه‌اندازی را قدم‌به‌قدم پیش می‌برد و خودش تونل را بالا می‌آورد؛ بار اول حدود
بیست دقیقه، که بیشترش در داشبورد متا می‌گذرد. نه شمارهٔ واقعی، نه کارت، نه
راستی‌آزمایی تجاری.

راهنمای کامل: [از WhatsApp](whatsapp.md).

---

## `comodor skills` — رویه‌هایی که دنبال می‌کند

```bash
comodor skills browse             # چه چیزهایی موجود است
comodor skills list               # شما چه دارید
comodor skills add review taste   # نصب چندتایی
comodor skills update             # تازه‌سازی نصب‌شده‌ها
comodor skills remove review
```

راهنمای کامل: [مهارت‌ها](skills.md).

---

## `comodor mcp` — سرورهای Model Context Protocol

```bash
comodor mcp list                  # شما چه دارید، و چه چیزی پیشنهاد می‌دهد
comodor mcp catalogue             # چه چیزهایی موجود است
comodor mcp add filesystem        # از کاتالوگ
comodor mcp custom NAME -- CMD    # فرمانی از خودتان
comodor mcp remote NAME URL       # یک سرور HTTP
comodor mcp enable NAME
comodor mcp disable NAME
comodor mcp remove NAME
comodor mcp test NAME             # وصل شدن و فهرست کردن ابزارهایش
```

راهنمای کامل: [سرورهای MCP](mcp.md).

---

## `comodor update` — رفتن به جدیدترین انتشار

```bash
comodor update --check     # چه چیزی آن بیرون هست، هیچ چیز را عوض نکن
comodor update             # انجامش بده
```

تشخیص می‌دهد که این نسخه چطور نصب شده — `uv`، `pipx`، `pip`، یا یک checkout از
سورس — و همان درست را استفاده می‌کند. یک checkout از سورس رها می‌شود: آن یکی
مال خودتان است.

---

## `comodor uninstall` — حذف کامل

```bash
comodor uninstall --dry-run    # فهرست چیزی که می‌رود
comodor uninstall              # بپرس، بعد انجامش بده
comodor uninstall --yes        # برای اسکریپت‌ها
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

قبل از حذف هر چیزی، همه‌چیز را نام می‌برد، و می‌گوید چه چیزی را پیدا نمی‌کند —
یک پوشهٔ `.comodor` در پروژه‌ای که استفاده کرده‌اید ولی تاریخچهٔ نشست‌هایش پاک
شده، نمی‌تواند نام برده شود، و به جای تظاهر همین را به شما می‌گوید.

---

## `comodor preview` — رابط کاربری در یک اندازهٔ مشخص

```bash
comodor preview 80x24
comodor preview 200x50 --svg wide.svg
```

یک فریم را رندر می‌کند و خارج می‌شود. برای بررسی یک ترمینال تنگ، یا برای گرفتن
اسکرین‌شات مفید است.

---

## متغیرهای محیطی

| | |
|---|---|
| `ANTHROPIC_API_KEY`، `OPENAI_API_KEY`، … | یک کلید، برای هر ارائه‌دهنده |
| `COMODOR_PROVIDER`، `COMODOR_MODEL` | تحمیل یک ارائه‌دهنده یا مدل |
| `COMODOR_HOME` | محل زندگی پیکربندی، مغز و نشست‌ها |
| `COMODOR_BANNER=0` | این اجرا بدون وردمارک |
| `COMODOR_NO_IMPORT=1` | پیشنهاد وارد کردن از عامل دیگر نده |
| `COMODOR_WEB_TOKEN` | یک توکن ثابت برای رابط تحت وب |
| `NO_COLOR` | بدون رنگ، در همه‌جا محترم |

کلیدی که در محیط باشد **هرگز در فایل پیکربندی شما نوشته نمی‌شود**. Export کردن
یک کلید به جای ذخیره‌اش یک تصمیم است، و `/save` به آن احترام می‌گذارد. به
[پیکربندی](configuration.md) نگاه کنید.

---

## کدهای خروج

| | |
|---|---|
| `0` | کار کرد |
| `1` | کار نکرد |
| `130` | شما قطعش کردید |

---

## ببینید

- [رابط کاربری](interface.md) — همان قدرت، به صورت تعاملی
- [پیکربندی](configuration.md) — دائمی کردن یک پرچم
- [عیب‌یابی](troubleshooting.md) — وقتی فرمانی کاری را که می‌گوید نمی‌کند
