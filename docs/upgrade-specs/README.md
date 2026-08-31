# 📐 مستندات توسعه — شکاف قابلیت‌های Comodor نسبت به Hermes-Agent

> **EN:** Implementation specifications for features found in NousResearch/hermes-agent but missing from Comodor's core. Each spec is bilingual: an English summary at the top, the detailed body in Persian. Written as blueprints for building a stronger, more competitive Comodor — additive designs that preserve Comodor's own differentiators (evidence-backed learning brain, prefix-cache-stable prompts, single-dependency philosophy).

این پوشه حاصل بررسی کامل هسته‌ی دو پروژه است:

| | Comodor | hermes-agent |
|---|---|---|
| زبان / وابستگی | Python، فقط `rich` | Python + Node |
| حلقه‌ی ایجنتی | ✅ با بودجه‌ی گام/زمان/هزینه | ✅ با ۳ مود API |
| یادگیری | ✅ مغز Reflex/Reflection مبتنی بر شواهد | ✅ حافظه‌ی منتخب + مهارت خودبهبود |
| جلسات | ✅ JSONL + FTS5 | ✅ SQLite + FTS5 |
| کانال‌ها | Telegram/Slack/WhatsApp (متن) | ۳۰+ پلتفرم با صوت و رسانه |
| زمان‌بندی | ❌ | ✅ cron ایجنتی کامل |
| صوت | ❌ | ✅ STT/TTS با ۱۰+ پرووایدر |

**فهرست اسناد:**

- [`00-gap-matrix.md`](00-gap-matrix.md) — ماتریس کامل مقایسه (اینجا شروع کنید)
- **۱. اتوماسیون** — [`cron-scheduler.md`](01-automation/cron-scheduler.md) · [`async-delegation.md`](01-automation/async-delegation.md) · [`programmatic-tool-calls.md`](01-automation/programmatic-tool-calls.md)
- **۲. کانال‌ها و رسانه** — [`discord-channel.md`](02-channels-media/discord-channel.md) · [`api-server-openai-compatible.md`](02-channels-media/api-server-openai-compatible.md) · [`webhook-channel.md`](02-channels-media/webhook-channel.md) · [`inbound-media.md`](02-channels-media/inbound-media.md) · [`voice-tts-stt.md`](02-channels-media/voice-tts-stt.md) · [`busy-input-modes.md`](02-channels-media/busy-input-modes.md)
- **۳. یادگیری و حافظه** — [`curated-memory.md`](03-learning-memory/curated-memory.md) · [`memory-providers.md`](03-learning-memory/memory-providers.md) · [`skill-lifecycle.md`](03-learning-memory/skill-lifecycle.md) · [`curator.md`](03-learning-memory/curator.md) · [`learning-graph.md`](03-learning-memory/learning-graph.md)
- **۴. زمینه** — [`context-references.md`](04-context/context-references.md) · [`session-lineage.md`](04-context/session-lineage.md)
- **۵. ابزارها** — [`vision.md`](05-tools/vision.md) · [`image-generation.md`](05-tools/image-generation.md) · [`mcp-expansion.md`](05-tools/mcp-expansion.md) · [`cross-platform-computer-use.md`](05-tools/cross-platform-computer-use.md)
- **۶. امنیت** — [`smart-approvals.md`](06-security/smart-approvals.md) · [`execution-backends.md`](06-security/execution-backends.md) · [`ssrf-guard.md`](06-security/ssrf-guard.md) · [`credential-pool.md`](06-security/credential-pool.md)
- **۷. پلتفرم** — [`plugin-system.md`](07-platform/plugin-system.md) · [`profiles.md`](07-platform/profiles.md) · [`insights.md`](07-platform/insights.md)

## ⚠️ آنچه Comodor برتری دارد — موقع منتقل‌کردن حذفش نکنید

**EN:** These Comodor strengths must survive every feature ported from Hermes. Do not "improve" them away:

1. **مغز یادگیری با شواهد عددی** (`learning/rules.py`) — قاعده‌ها شمارش و شاهد دارند («۳۱ از ۳۴ رشته با کوتیشن تکی»)، با نیم‌عمر ۴۵ روز decay می‌شوند. حافظه‌ی متنی Hermes جایگزین این نمی‌شود؛ مکملش باشد.
2. **Briefing در پیام کاربر، نه system prompt** — دلیلِ پایداری prefix-cache (کش ۸۶٪). هر قابلیتی که وسط جلسه system prompt را تغییر دهد، ممنوع.
3. **`mine_only()` در config** — مقادیر قرضی از پروژه/env هرگز روی دیسک ذخیره نمی‌شوند. قابلیت‌های جدید باید از همین مکانیزم عبور کنند.
4. **Overflow = انتقال نه حذف** (`tools/overflow.py`) — خروجی بزرگ به فایل می‌رود با راهنمای ادامه؛ الگوی همه‌ی ابزارهای جدید.
5. **تک‌وابستگی** — چیزی به `pyproject.toml` اضافه نشود مگر اجبار مطلق؛ حتی‌الامکان stdlib.
6. **Fail-closed و شفاف** — بن‌بست‌ها با پیام قابل‌فهم، نه سکوت؛ الگوی `channels/settings.py` و `permissions.py`.

## نقشه‌ی راه پیشنهادی (اولویت رقابتی)

**EN:** Suggested order — P0 items close the most visible user-facing gaps first.

- **P0 (قدرت نمایشی فوری):** cron ایجنتی · رسانه‌ی ورودی کانال‌ها · lifecycle مهارت خودبهبود · حافظه‌ی منتخب
- **P1 (عمق و عمومیت):** Discord · API Server سازگار OpenAI · voice/TTS · async delegation · execute_code · context references · vision · smart approvals
- **P2 (بلوغ پلتفرم):** MCP کامل · backendهای اجرای ایزوله · plugin system · profiles · insights · تولید تصویر

## قواعد مشترک همه‌ی specها

- **افزودنی‌اند، نه بازطراحی:** هیچ فایل موجودی حذف یا معکوس نمی‌شود؛ ماژول‌های جدید در `src/comodor/<module>/`، ابزارها در `src/comodor/tools/` ثبت می‌شوند.
- **کانفیگ لایه‌بندی‌شده:** هر کلید جدید به `config.py` اضافه می‌شود و از فیلتر پروژه (`config.project_filtered`) عبور می‌کند.
- **ریسک ابزار:** هر ابزار جدید با `SAFE/WRITE/DANGEROUS` در `tools/registry.py` ثبت و از همان گیت مجوز می‌گذرد.
- **آفلاین‌پسند:** امکان خاموش‌کردن کامل هر قابلیت از کانفیگ؛ پیش‌فرض‌ها محافظه‌کارانه.
