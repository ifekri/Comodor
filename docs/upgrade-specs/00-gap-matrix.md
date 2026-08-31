# ماتریس مقایسه‌ی کامل — Comodor × Hermes-Agent

> **EN:** Full gap matrix between Comodor and NousResearch/hermes-agent, verified against both codebases. ❌ = absent in Comodor core, ⚠️ = partial, ✅ = present. Each row links to its implementation spec. Rows marked «برتری Comodor» are features where Comodor is ahead — listed so they are never dropped during porting.

## ۱. اتوماسیون و زمان‌بندی

| قابلیت | hermes | Comodor | Spec |
|---|---|---|---|
| Cron ایجنتی (زمان‌بندی NL، تحویل به پلتفرم، incidents) | ✅ `cron/scheduler.py` | ❌ هیچ زمان‌بندی‌ای وجود ندارد | [`cron-scheduler.md`](01-automation/cron-scheduler.md) |
| Delegation ناهمگام (background + رویداد تکمیل به‌صورت turn) | ✅ `tools/async_delegation.py` | ⚠️ فقط sync تک‌سطحی در `tools/delegate.py` | [`async-delegation.md`](01-automation/async-delegation.md) |
| فراخوانی ابزار از Python (RPC) | ✅ `tools/code_execution_tool.py` | ⚠️ `run_python` به ابزارها دسترسی ندارد | [`programmatic-tool-calls.md`](01-automation/programmatic-tool-calls.md) |

## ۲. کانال‌ها و رسانه

| قابلیت | hermes | Comodor | Spec |
|---|---|---|---|
| Discord | ✅ آداپتور کامل + voice channel | ❌ | [`discord-channel.md`](02-channels-media/discord-channel.md) |
| API Server سازگار با OpenAI | ✅ برای Open WebUI و… | ❌ | [`api-server-openai-compatible.md`](02-channels-media/api-server-openai-compatible.md) |
| کانال Webhook عمومی | ✅ `gateway/webhook` | ❌ | [`webhook-channel.md`](02-channels-media/webhook-channel.md) |
| رسانه‌ی ورودی (voice-note→STT، عکس→vision، فایل) | ✅ | ❌ کانال‌ها فقط متن‌اند | [`inbound-media.md`](02-channels-media/inbound-media.md) |
| TTS / STT / voice mode | ✅ ۱۰+ پرووایدر | ❌ | [`voice-tts-stt.md`](02-channels-media/voice-tts-stt.md) |
| مودهای ورودی هنگام اشغال (interrupt/queue/steer) + delivery ledger | ✅ | ⚠️ فقط صف ساده | [`busy-input-modes.md`](02-channels-media/busy-input-modes.md) |

## ۳. یادگیری و حافظه

| قابلیت | hermes | Comodor | Spec |
|---|---|---|---|
| حافظه‌ی منتخب (MEMORY/USER) + review پس‌زمینه‌ای هر turn | ✅ `agent/background_review.py` | ❌ فقط lessons + rules با ثابت‌سازی | [`curated-memory.md`](03-learning-memory/curated-memory.md) |
| پرووایدرهای حافظه‌ی بیرونی (Honcho/Mem0/…) | ✅ ۸ پرووایدر | ❌ | [`memory-providers.md`](03-learning-memory/memory-providers.md) |
| ساخت/پچ خودبهبود مهارت + linter + usage + ledger | ✅ `tools/skill_manager_tool.py` | ⚠️ فقط `skills/propose.py` با تأیید کاربر | [`skill-lifecycle.md`](03-learning-memory/skill-lifecycle.md) |
| Curator (کهولت/آرشیو/ادغام مهارت‌ها) | ✅ `agent/curator.py` | ❌ | [`curator.md`](03-learning-memory/curator.md) |
| گراف یادگیری (/journey) | ✅ `agent/learning_graph.py` | ❌ | [`learning-graph.md`](03-learning-memory/learning-graph.md) |

> **برتری Comodor:** قاعده‌های مبتنی بر شواهد عددی، decay نیم‌عمر، associations شمارشی بدون embedding، آستانه‌های تأیید چندمنبعی. این‌ها جایگزین نشوند — specs بخش ۳ مکمل‌اند.

## ۴. مدیریت زمینه

| قابلیت | hermes | Comodor | Spec |
|---|---|---|---|
| ارجاع زمینه با @ (فایل/دیفر/git/url در خط فرمان TUI) | ✅ `agent/context_references.py` | ❌ فقط attach فایل | [`context-references.md`](04-context/context-references.md) |
| Lineage جلسه + کامپرشن چند-ترایگری با شکافتن SQLite session | ✅ `hermes_state.py` | ⚠️ کامپرشن دارد ولی بدون lineage و بدون شکافتن session | [`session-lineage.md`](04-context/session-lineage.md) |

> **برتری Comodor:** سه‌مرحله‌ای «ارزان‌ترین اول» (اسکرین‌شات → خوانش منقضی → خلاصه) و حفاظت از درخواست اصلی در کامپرشن.

## ۵. ابزارها

| قابلیت | hermes | Comodor | Spec |
|---|---|---|---|
| Vision (تحلیل عکس ورودی کاربر) | ✅ `tools/vision` | ⚠️ فقط اسکرین‌شات خودش در `computer` | [`vision.md`](05-tools/vision.md) |
| تولید تصویر | ✅ FAL/چند پرووایدر | ❌ | [`image-generation.md`](05-tools/image-generation.md) |
| MCP کامل (resources/prompts/sampling/OAuth) | ✅ | ⚠️ فقط tools | [`mcp-expansion.md`](05-tools/mcp-expansion.md) |
| computer use روی macOS/Linux | ✅ (via cua-driver) | ❌ فقط Windows (`desktop/win32.py`) | [`cross-platform-computer-use.md`](05-tools/cross-platform-computer-use.md) |

## ۶. امنیت

| قابلیت | hermes | Comodor | Spec |
|---|---|---|---|
| Smart approvals (ارزیابی ریسک با LLM کمکی + mining اجازه‌ها) | ✅ `tools/approval.py` | ❌ تیرهای ثابت SAFE/WRITE/DANGEROUS | [`smart-approvals.md`](06-security/smart-approvals.md) |
| Backendهای اجرای ایزوله (Docker/SSH/Modal/…) برای shell | ✅ ۷ backend | ⚠️ فقط host + Docker image | [`execution-backends.md`](06-security/execution-backends.md) |
| SSRF guard (لیست URLها، حلقوی، fail-closed) | ✅ | ⚠️ `web.py` محدودیت کم دارد | [`ssrf-guard.md`](06-security/ssrf-guard.md) |
| Credential pool (چند کلید با چرخش خودکار) | ✅ `agent/credential_pool.py` | ❌ یک کلید به‌ازای پرووایدر | [`credential-pool.md`](06-security/credential-pool.md) |

> **برتری Comodor:** HMAC تأییدشده‌ی webhook واتساپ، گیت مجوز سه‌سطحی ساده‌ومفهوم، checkpoints با journal، redaction فراگیر.

## ۷. پلتفرم

| قابلیت | hermes | Comodor | Spec |
|---|---|---|---|
| Plugin system (ابزار/hook/CLI از pip یا پوشه) | ✅ `hermes_cli/plugins.py` | ❌ فقط MCP/skills | [`plugin-system.md`](07-platform/plugin-system.md) |
| پروفایل‌های همزمان (`hermes -p name`) | ✅ | ❌ یک `~/.comodor` واحد | [`profiles.md`](07-platform/profiles.md) |
| آمار مصرف (/usage، /insights) | ✅ `agent/insights.py` | ⚠️ فقط `/cost` درون-جلسه | [`insights.md`](07-platform/insights.md) |

## ۸. چیزهایی که hermes دارد و عمداً توصیه به انتقال نشد

> **EN:** Hermes features deliberately *not* specced, with reasons — Comodor should not copy these.

- **TUI و skin engine** — TUI اختصاصی Comodor (three-thread, hit-test rectangles) بالاتر است؛ بازطراحی معنا ندارد.
- **سوگند SOUL.md / personality presets** — Comodor از `COMODOR.md` و playbook استفاده می‌کند؛ افزودن لایه‌ی شخصیت، cache پایدار را می‌شکند. (در صورت نیاز آینده: فایل جدا و بیرون از prefix ثابت.)
- **Trajectory generation / batch runner** — فقط برای آموزش مدل است؛ Comodor مسیرش بنچ داور-برنامه‌ای است.
- **Honcho به‌عنوان پیش‌فرض حافظه** — پرووایدر بیرونی = وابستگی سرویس؛ در spec پرووایدرها فقط به‌صورت لایه‌ی اختیاری آمده.
- **پشتیبانی Windows نصب native و Termux** — Comodor از قبل installer دارد؛ تکرار لازم نیست.
