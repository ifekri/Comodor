# Spec: زمان‌بند ایجنتی (Cron)

> **EN summary:** Comodor has no scheduler at all — nothing runs an agent turn on a timer. Hermes proves this is the single highest-impact missing feature: natural-language scheduled jobs ("every weekday 9am, check CI and ping me on Telegram") that run a fresh agent turn and deliver output to any connected channel. This spec adds a `src/comodor/cron/` module reusing the existing channel daemon (`channels/daemon.py`), OS autostart units (`channels/unit.py`), and provider stack, with Comodor-style fail-closed drift guards and no-token script mode. Priority **P0**, effort **L**.

## قابلیت در hermes چطور است

مرجع: `cron/scheduler.py`، `cron/jobs.py`، `tools/cronjob_tools.py` در hermes-agent.

- ابزار واحد `cronjob` با اکشن‌های create/list/update/pause/resume/run/remove؛ کارها در `~/.hermes/cron/jobs.json` با نوشتن اتمیک.
- انواع زمان‌بندی: یک‌باره (`in 30m`، ISO)، بازه‌ای (`every 2h`)، زبان طبیعی (`every monday 9am`، `weekdays at 9am`، `noon`) با کامپایل به croniter، و عبارت cron خام.
- اجرا: تیک هر ۶۰ ثانیه درون gateway با `.tick.lock`؛ هر اجرا یک **AIAgent تازه بدون تاریخچه** با مهارت‌های پیوسته.
- **مدل در لحظه‌ی شلیک:** pin هر job → `cron.model` → snapshot سراسری؛ «drift» = fail-closed (رد اجرا + یک هشدار).
- تحویل به هر پلتفرم (`origin`, `telegram:<chat>#<topic>`, `discord:#chan`, `all`, ترکیب با کاما)؛ توکن `[SILENT]` تحویل را قطع می‌کند ولی خروجی ذخیره می‌شود؛ کارهای شکسته همیشه تحویل می‌روند.
- **حلقه‌ها بسته می‌شوند:** ابزارهای مدیریت cron داخل اجرای cron غیرفعال‌اند؛ `allow_agent_scheduling` پیش‌فرض خاموش.
- دیده‌بانی: `executions.db` با حالت claimed→running→completed/failed/unknown؛ `misfire_grace_minutes`؛ `failure_streak` (پیش‌فرض ۳) و incident ها keyed به امضای خطا.
- مود no-agent: اسکریپت زیر `$HERMES_HOME/scripts/` بدون هیچ توکنی اجرا و stdout مستقیم تحویل می‌شود؛ خط پایانی `{"wakeAgent": false}` = تیک خاموش.
- زنجیره: `context_from` (خروجی job بالادستی) و `continuity` (خروجی قبلی خود job).
- قابل-ادامه: با `attach_to_session` خروجی cron به‌صورت turn برچسب‌دار در مکالمه‌ی مبدأ نوشته می‌شود تا کاربر بتواند ادامه دهد.

## جای آن در Comodor

- **زیرساخت آماده:** `channels/daemon.py` (اجراهای foreground/detached)، `channels/unit.py` (systemd/launchd/schtasks)، `channels/settings.py` (بازخوانی کانفیگ حین اجرا)، `session/store.py` (JSONL)، `providers/gateway.py`.
- **جدید:** ماژول `src/comodor/cron/` با: `jobs.py` (موجودیت + ذخیره‌ی JSON اتمیک در `~/.comodor/cron/jobs.json` با الگوی `permissions.py`)، `parse.py` (تجزیه‌ی NL/interval/cron — حداقل با پارسر cron دستی ۵-فیلدی و قالب‌های NL ساده؛ بدون `croniter` مگر مجوز وابستگی)، `scheduler.py` (حلقه‌ی تیک + قفل)، `runner.py` (ساخت turn ایجنتی تازه از طریق همان مسیر `agent/loop.py` که `cli.py run` استفاده می‌کند)، `deliver.py` (تحویل از طریق آداپتورهای کانال موجود).
- **تعامل با یادگیری:** اجرای cron از briefing مغز استفاده کند ولی در `learning/store.db` با scope جدا ثبت شود تا جلسات cron، قواعد کاربر را آلوده نکنند (درون Comodor «detached» پیش‌فرض باشد، همان الگوی hermes).

## طراحی پیشنهادی

```
CLI:    comodor cron list|add|edit|pause|resume|run|remove|incidents
ابزار:  cronjob (ریسک DANGEROUS — می‌تواند کار خود-زمان‌بند ایجاد کند)
        → داخل اجرای cron این ابزار اصلاً advertise نمی‌شود (ضد حلقه‌ی بی‌پایان)
کانفیگ: cron.enabled=false, cron.model=null, cron.max_concurrency=2,
        cron.misfire_grace_minutes=10, cron.failure_streak=3,
        cron.wrap_response=true, cron.delivery_default="origin"
```

- **Fail-closed:** اگر مدلِ pin‌شده در دسترس نباشد، اجرا رد شود با یک هشدار — نه سقوط به مدل دیگر بی‌سروصدا (هزینه‌ی نامعلوم = ممنوع).
- **تحویل پیش‌فرض `origin`:** جلسه‌ی مبدأ در FTS موجود قابل بازیابی است؛ برای قابل-ادامه‌بودن، خروجی به‌صورت turn برچسب‌دار `[Cron: <name>]` به transcript مبدأ append شود.
- **No-agent mode:** اسکریپت زیر `~/.comodor/cron/scripts/` (exec حداکثر ۶۰ ثانیه، env بدون کلید)، خط پایانی `{"wakeAgent": false}` همان‌طور.
- **امنیت:** مجوزهای تحویل از همان allowlist کانال‌های موجود (`telegram/…`, `slack/…`)؛ cron نمی‌تواند گیرنده‌ی خارج از allowlist داشته باشد؛ کلیدهای API هرگز در jobs.json ذخیره نشوند (فقط نام پرووایدر).
- **TUI:** پنل cron در sidebar موجود + دستور `/cron`؛ ویرایشگر job یک فرم `questions.py` باشد.

## نقشه‌ی پیاده‌سازی

1. `cron/jobs.py` — schema: `{id, name, schedule{kind,expr,tz}, prompt, model_pin, delivery[], skills[], enabled, repeat, state, last_fire, last_error, failure_streak}`؛ نوشتن اتمیک + قفل فایل.
2. `cron/parse.py` — پنج قالب: ISO/`in <dur>`/`every <dur>`/NL ساده (روزهای هفته + ساعت)/cron ۵-فیلدی. خطای تجزیه = پیشنهاد نزدیک‌ترین قالب درست.
3. `cron/scheduler.py` — نخ daemon با تیک ۶۰ ثانیه، `tick.lock` (فایل قفل + PID)، بارگذاری کارهای سررسید.
4. `cron/runner.py` — یک `loop.py` headless همان مسیر `run --json`؛ ثابت‌سازی مدل snapshot؛ ثبت اجرا در SQLite (`cron/executions.db` با FTS برای متن خروجی) با حالت‌های hermes.
5. `cron/deliver.py` — mapping گیرنده → آداپتور کانال؛ صف تحویل با retry ۳ بار و پاک‌سازی ۷ روزه (الگوی delivery ledger در spec 02).
6. ثبت ابزار `cronjob` در `tools/registry.py` با گیتِ «خارج از اجرای cron بودن» در check_fn.
7. `cli.py`: ساب‌کامند `cron` + یکپارچه‌سازی با `channels/daemon.py` (شروع/توقف هم‌زمان با daemon کانال‌ها).
8. تست: با `providers/fake.py` — زمان‌بندی مصنوعی (تیک دستی)، drift guard، حلقه‌ی cron-داخل-cron باید رد شود.

## پذیرش و تست

- `comodor cron add "هر روز ساعت 9 صبح خلاصه‌ی git log دیروز را به تلگرام بفرست"` کار کند.
- تیک در حالت sleep لپ‌تاپ جا افتاده → misfire grace پیام بدهد و دوباره شلیک نکند.
- قطع process وسط اجرا → restart وضعیت `unknown` نشان دهد و auto-rerun نکند.
- کار شکسته ۳ بار پشت‌سرهم → nudge به کانال مبدأ با پیشنهاد pause.
- ۱۶۶۴ تست موجود نگذرد نشود؛ `test_prefix_stability.py` دست‌نخورده بماند.
