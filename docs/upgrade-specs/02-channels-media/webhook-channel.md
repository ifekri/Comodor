# Spec: کانال Webhook عمومی

> **EN summary:** Hermes has a generic webhook adapter — any external system (CI, monitoring, Git hosting) can POST an event and get agent processing delivered back. Comodor has webhooks *inbound* only for WhatsApp (with its excellent HMAC verification) but no general-purpose webhook channel. This spec generalizes the existing WhatsApp webhook server's security posture into a generic `comodor webhook` channel with per-source tokens, HMAC verification, prompt templating, and optional delivery. Priority **P1**, effort **S–M**.

## قابلیت در hermes چطور است

- آداپتور `webhook` در gateway + CLI `hermes webhook` برای اشتراک‌های داینامیک (prompt + skills + delivery per subscription).
- هر اشتراک: trigger HTTP → prompt ساخته‌شده از payload → اجرای ایجنتی → تحویل به کانال دلخواه.

## جای آن در Comodor

- موجود: `whatsapp/webhook.py` (HTTP server با HMAC-SHA256 روی بایت خام و مقایسه‌ی constant-time — این الگو مستقیماً reuse شود)، `channels/daemon.py`، `net/http.py`، `agent/loop.py`.
- جدید: `src/comodor/webhook/` با `server.py`، `routes.py`، `subs.py` (اشتراک‌ها).

## طراحی پیشنهادی

```
CLI:      comodor webhook add <name> --path /gh --secret ... --template ...
          comodor webhook list|test|remove
کانفیگ:   webhook.enabled=false, webhook.bind=127.0.0.1, webhook.port=8790,
          webhook.subs={name: {path, secret, template, delivery, allow_writes}}
امنیت:
  - HMAC-SHA256 با کلید per-subscription روی بایت خام، constant-time (الگوی whatsapp)
  - بدون secret → مسیر رد با 404 (نه 401 — نبود endpoint لو نرود)
  - payload سقف ۲۵۶KB؛ اکشن‌های درخواستی: fail-closed
  - پاسخ sync پیش‌فرض: {"status":"accepted"} — اجرا async در پس‌زمینه
```

- **قالب prompt:** template ساده با placeholderهای JSON-path (`{.pull_request.title}`) — بدون وابستگی؛ خطاهای path = رد با لاگ.
- **تحویل:** پیش‌فرض همان درخواست‌دهنده (بدنه‌ی JSON پاسخ بعد از اتمام تا timeout ۱۰ ثانیه؛ در غیر اینصورت async و آدرس `reply_url` اختیاری)؛ یا کانال ثبت‌شده.
- **تراست جدا از کانال‌ها:** webhook هیچ‌وقت دسترسی write پیش‌فرض ندارد حتی اگر کانال مقصد اجازه دهد (`allow_writes` per-sub، پیش‌فرض false).
- **دستور `/webhook` در TUI** برای دیدن آخرین رویدادها و وضعیت اشتراک‌ها؛ ثبت هر رویداد در فصل جداگانه‌ی JSONL برای دیباگ.

## نقشه‌ی پیاده‌سازی

1. `webhook/server.py` — ThreadingHTTPServer (الگوی web/server.py)، routing per-path، هدرهای CORS صفر.
2. `subs.py` — ذخیره در `~/.comodor/webhook/subs.json` (همان نوشتن اتمیک + 0600).
3. template engine مینیمال (JSON-path با یک tokenizer ۱۰۰ خطی).
4. اتصال به runner مشترک (همان مسیر headless `run --json` که cron هم استفاده می‌کند — بازاستفاده از spec 01).
5. تست: HMAC غلط/نبود، payload بزرگ، template خراب، اجرای موازی ۵ رویداد.

## پذیرش و تست

- GitHub webhook با secret → روی هر push یک خلاصه‌ی diff به تلگرام allowlist برود.
- امضای جعلی (۱ بایت تغییر) → 404 و هیچ اجرایی نه.
- شلیک ۱۰ رویداد هم‌زمان → صف منظم، هیچ رویدادی دور ریخته نشود (at-least-once با ledger).
