# Spec: Delegation ناهمگام (background subagents)

> **EN summary:** Comodor's `delegate` tool is synchronous and single-level: the parent blocks until the child finishes. Hermes supports background delegation — the parent keeps working while children run, and completion events surface as a *new turn* when the agent goes idle (never spliced mid-conversation, to protect alternation and prefix-cache integrity). This spec adds `background=true` to the existing `delegate` tool plus a runtime control plane (list/steer/stop), rejecting-not-queuing on overload, and crash-safe persistence. Priority **P1**, effort **M**.

## قابلیت در hermes چطور است

مرجع: `tools/delegate_tool.py`، `tools/async_delegation.py`، `agent/subagent_lifecycle.py`.

- `delegate_task(background=true)`: اجرای daemon-level با concurrency cap (پیش‌فرض ۳) و **reject-don't-queue** — ادمین‌قابل تنظیم نیست که صف انباشته شود؛ یک مدل وحشی نمی‌تواند کار انبار کند.
- Completion events به `process_registry.completion_queue` می‌روند؛ CLI/gateway وقتی idle شد یک turn تازه از آن می‌سازد — «تکمیل‌ها هرگز وسط مکالمه splice نمی‌شوند» (invariant سخت).
- Payload رویداد خودکفاست (goal، context، toolsets، وضعیت، خلاصه‌ی نتیجه) چون والد ممکن است در میانه‌ی زمینه‌ی دیگری باشد.
- پایداری در SQLite با سقف retry، سقف replay ۴۸ ساعته، بازیابی بعد از crash.
- Staleness مبتنی بر پیشرفت نه ساعت‌دیواری؛ فرزند گیرکرده interrupt و با برچسب `stalled` نهایی می‌شود.
- کنترل‌پلن: `list`/`steer`/`stop` + heartbeat + تشخیص فرزند گیرکرده؛ `interrupt_all` روی `/stop`.
- Parent خروجی فرزند را با سقف بودجه‌ای (۵۰٪ از headroom باقیمانده، کف ~۲۰۰۰ کاراکتر) می‌بیند؛ فرزند موظف به خلاصه‌ی نتیجه-محور است.

## جای آن در Comodor

- موجود و قابل‌استفاده: `tools/delegate.py` (spawn sync فعلی)، `agent/spawn.py` (ساخت فرزند، یک‌سطحی، بدون مغز)، `events.py` (EventBus — تنها مرز نخ)، `session/store.py` (JSONL)، `agent/context.py` (بودجه‌ی توکن).
- **تغییرات:**
  1. `spawn.py`: پارامتر `background` — نخ‌های worker با `ThreadPoolExecutor` (الگوی اجرای موازی SAFE موجود در `agent/loop.py`)، پیش‌فرض ۳، **رد به‌جای صف**: اگر همه‌ی اسلات‌ها مشغول است، ابزار همان لحظه خطای روشن برگرداند با «دوباره بعد از اتمام X امتحان کن».
  2. `events.py`: نوع رویداد `DelegationCompleted` به EventBus اضافه شود؛ TUI در حالت idle (ورودی در انتظار prompt) آن را به یک turn داخلی «[Background task finished]» تبدیل کند — هرگز وسط استریم یا بین tool-call و نتیجه.
  3. پایداری: وضعیت delegation در همان JSONL جلسه‌ی والد به‌عنوان رکورد سیستمی (نه پیام LLM) — بازیابی بعد از crash یعنی فایل خوانده شود و کارهای ناتمام با برچسب `lost` گزارش شوند (بدون شبیه‌سازی «شاید هنوز زنده‌اند»).
  4. کنترل‌پلن: `/delegates` در TUI + در sidebar موجود (کارت‌های running sub-agents) دکمه‌های stop/steer.
  5. خلاصه‌ی نتیجه: سقف داینامیک از `context.py` بخواند؛ خود الگوی overflow «انتقال نه حذف» (`tools/overflow.py`) برای خروجی کامل فرزند اعمال شود — خلاصه در پیام، متن کامل در فایل.

## طراحی پیشنهادی

```
ابزار:  delegate (به‌روزرسانی schema: background: bool, label: str)
کانفیگ: delegation.max_background=3, delegation.completion_summary_max=24000,
        delegation.stall_check_seconds=30
TUI:    /delegates list|stop <id>  + کارت‌های sidebar
```

- **invariant alternation:** رویداد تکمیل فقط در مرز turn اعمال شود (همان نقطه‌ای که `agent/context.py` اجازه‌ی کامپرشن می‌دهد) — با invariant موجود «کامپرشن فقط مرز بدون tool-call باز» هم‌راستاست.
- اجرای فرزند background همان مسیر `spawn.py` فعلی باشد (تک‌سطحی، بدون delegate دوباره) — عمق‌بخشی هرمی یک scope آینده است.
- fail-closed: اگر EventBus در دسترس نیست (حالت headless `run` بدون TUI)، background=true رد شود با پیشنهاد `background=false`.

## نقشه‌ی پیاده‌سازی

1. توسعه‌ی `agent/spawn.py` با executor و اسلات‌ها + شمارش زنده در EventBus.
2. `tools/delegate.py`: schema جدید + اعتبارسنجی رد-به‌جای-صف با پیام شفاف.
3. `agent/loop.py`: نظرسنجی تکمیل‌ها در انتظار ورودی (TUI و `run`) و ساخت turn سیستم-برچسب‌دار.
4. `ui/app.py`: دستور `/delegates` + اتصال کارت‌های sidebar به executor.
5. تزریق خلاصه با بودجه‌ی توکن از `context.py`؛ متن کامل → `tools/overflow.py`.
6. تست: crash وسط اجرا، پرشدن اسلات‌ها، رویداد در حین استریم (باید صبر کند)، رزومه‌ی جلسه.

## پذیرش و تست

- والد بتواند در حین ۲ فرزند background به کاربر جواب بدهد؛ تکمیل‌ها به‌صورت turn جدا و ترتیب‌سالم ظاهر شوند.
- `/delegates` نشان دهد چه چیزی می‌دود، چقدر گام مصرف شده، و stop فوراً قطع کند.
- کشتن process والد → در resume، کارهای background با برچسب `lost` گزارش شوند — نه ناپدید شدن خاموش.
