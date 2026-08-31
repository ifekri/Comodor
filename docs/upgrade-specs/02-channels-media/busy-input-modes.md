# Spec: مودهای ورودی هنگام اشغال + ledger تحویل

> **EN summary:** When a message arrives while the agent is mid-turn, Hermes offers three user-selectable behaviors: `interrupt` (redirect the active turn at the next tool boundary, keeping completed work), `queue`, and `steer` — plus a durable delivery ledger that redelivers replies lost to a crash. Comodor's channels queue silently; users on phones cannot redirect a running task except by sending Esc through the TUI. This spec adds the three modes per-channel, a durable delivery ledger for the channel daemons, and a circuit breaker per adapter. Priority **P1**, effort **M**.

## قابلیت در hermes چطور است

- `interrupt` (پیش‌فرض): turn فعال در مرز بعدی tool-result به پیام جدید هدایت می‌شود؛ کارِ انجام‌شده به‌صورت checkpoint نگه داشته می‌شود.
- `queue`: صف FIFO؛ `steer`: پیام جدید به‌عنوان دستور اصلاحی به همان turn تزریق می‌شود.
- **delivery ledger** (`gateway/delivery_ledger.py`): at-least-once — بعد از crash، پاسخ‌های تحویل‌نشده با پیشوند «♻️ Recovered reply» و ۳ تلاش و تازگی ۲۴ ساعته دوباره می‌روند؛ پاک‌سازی ۷ روزه.
- **circuit breaker:** آداپتوری که پشت‌سرهم خطای retryable بدهد، auto-pause می‌شود؛ `/platform resume` دستی.
- idle reset per-platform (تلگرام ۲۴۰ دقیقه، دیسکورد ۶۰).

## جای آن در Comodor

- موجود: صف پیام در `telegram/bot.py` و مشابه‌ها (رفتار فعلی = queue بی‌انتخاب)، `agent/loop.py` (نقاط cooperative cancellation بین گام‌ها — نقطه‌ی امن interrupt همانی است)، `channels/daemon.py`، `session/store.py` (JSONL append-only — ایده‌آل برای ledger).
- جدید: `channels/busy.py` (سه مود)، `channels/ledger.py` (تحویل ماندگار)، `channels/breaker.py`.

## طراحی پیشنهادی

```
کانفیگ (per-channel در telegram/whatsapp/slack/discord):
  <ch>.busy_mode=queue        # queue | interrupt | steer
  <ch>.idle_reset_minutes=…   # جدا per-channel
سطح TUI (سراسری):
  ui.busy_mode=queue          # برای پیام‌های رسیده در حین اجرای TUI (مثلاً از cron)
ledger:
  channels/ledger.py — هر پاسخ outbound قبل از ارسال append می‌شود:
  {platform, chat_id, session, body_hash, body_ref, status: pending|sent|failed, attempts, ts}
  روی start دیمون: هر pending با تازگی <24h دوباره با پیشوند «♻️ (تلاش دوباره)»
breaker:
  خطای retryable پشت‌سرهم ۵ بار → آداپتور pause + nudge به allowlist admins
  `/platforms` در کانال: وضعیت + resume
```

- **interrupt در Comodor:** پیام جدید شلیک `events.py` cancel موجود باشد ولی با پیام برچسب‌دار «[کار قبلی نیمه‌کاره ماند در گام N — خروجی checkpoint نگه داشته شد]» و checkpoint از `safety/checkpoints.py` (که از قبل هر write را snapshot می‌کند — رایگان است!).
- **steer:** پیام جدید به‌عنوان user message در `agent/context.py` درج شود و LLM همان پاسخ در-گردش را با زمینه‌ی جدید بازنویسی کند — v1 ساده: فقط interrupt و queue؛ steer وقتی تزریق mid-turn امن شد.
- **dedup:** envelope-ACK الگوی `slack/socket.py` برای واتساپ/تلگرام هم اعمال شود (پیام دوباره پس از reconnect، دوبار اجرا نشود).

## نقشه‌ی پیاده‌سازی

1. `channels/busy.py` — استراتژی مشترک سه‌کاناله به‌جای صف کپی‌شده در هر bot.py؛ رفع تکرار فعلی.
2. `agent/loop.py`: تابع `cancel_with_checkpoint(reason)` که cancel + ثبت وضعیت گام و پیام برچسب‌دار ترکیب کند.
3. `channels/ledger.py` — JSONL با بازیابی در start؛ ادغام در سه دیمون.
4. breaker + `/platforms` در هر بات (دستورات موجود در `*/commands.py` گسترش یابد).
5. تست: crash بعد از تولید پاسخ قبل از ارسال → resume تحویل بدهد؛ interrupt وسط write → checkpoint موجود برگردد.

## پذیرش و تست

- `busy_mode=interrupt` + پیام جدید در حین اجرا → کار قبلی متوقف با پیام شفاف، کار جدید شروع.
- کشتن daemon بعد از تولید پاسخ → اجرای دوباره، همان پاسخ یک‌بار با پیشوند ♻️.
- شبکه‌ی قطع ۵ دقیقه → breaker پیام می‌دهد و بعد از resume خودش برمی‌گردد.
- رفتار پیش‌فرض تغییر نکند (queue) — فقط opt-in.
