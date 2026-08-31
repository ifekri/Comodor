# Spec: Smart Approvals — ارزیابی ریسک با مدل کمکی + approval mining

> **EN summary:** Comodor classifies commands with fixed tiers (SAFE/WRITE/DANGEROUS) and a DEFAULT_DENY list — predictable, but a user running the same benign-but-unusual command fifty times clicks "approve" fifty times, training them to click blindly. Hermes's smart mode uses a cheap auxiliary LLM to risk-assess non-obvious commands (low→auto-approve, dangerous→auto-deny, uncertain→ask the human) with fail-closed timeout, plus "approval mining" that turns past manual approvals into allowlist proposals. This spec adds both, layered *on top of* the existing tiers — the tier system stays the fast path; the LLM only sees what the tiers can't classify. Priority **P1**, effort **M**.

## قابلیت در hermes چطور است

مرجع: `tools/approval.py`.

- `approvals.mode = smart | manual | off`; در smart: LLM کمکی risk-assess می‌کند (low auto-approve، dangerous auto-deny، uncertain → آدم)؛ timeout ۳۰۰ ثانیه = fail-closed؛ مودهای headless (cron و…) پیش‌فرض deny.
- YOLO همه را رد می‌کند به‌جز UNRECOVERABLE_BLOCKLIST (rm -rf /، fork bomb، mkfs، dd به بلاک‌دستگاه، curl|sh).
- deny globs کاربر روی variants deobfuscated اجرا می‌شود؛ فهرست تریگرهای مفصل (chmod 777، DROP/DELETE بدون WHERE، نوشتن در /etc و ~/.ssh و .env، docker -H، kill فرایندهای خودش و…).
- **approval mining:** `hermes approvals suggest --apply` از تاریخچه‌ی state.db پیشنهادهای allowlist استخراج می‌کند (کلاس‌های تخریبی هرگز).
- allowlist دائم `command_allowlist`؛ تأیید از خود چت کانال.

## جای آن در Comodor

- موجود: `safety/permissions.py` (گیت سه‌سطحی + timeout=deny)، `tools/shell.py`، `safety/checkpoints.py`، `session/search.py` (تاریخچه‌ی تصمیم‌ها در JSONL)، `learning/store.py` (جای ذخیره‌ی allowlist یادگرفته‌شده).
- جدید: `src/comodor/safety/smart.py` + `src/comodor/safety/mining.py`.

## طراحی پیشنهادی

```
لایه‌بندی تصمیم (ترتیب):
  1. SAFE/WRITE طبقه‌بندی موجود → همان مسیر سریع، بدون LLM
  2. DEFAULT_DENY و UNRECOVERABLE blocklist → هرگز توسط LLM قابل رد نیست
  3. allowlist کاربر → auto-approve (بدون LLM)
  4. smart mode (opt-in، safety.smart_approvals=true):
     فراخوانی مدل کمکی (پیش‌فرض: مدل ارزان همان پرووایدر؛ سقف ۵ ثانیه؛
     timeout = deny همانند فلسفه‌ی فعلی) با prompt ساده: این دستور چه می‌کند؟
     کدام فایل‌ها/شبکه را لمس می‌کند؟ بازگشتی؟ خروجی: allow|deny|ask
     - فقط دستور، بدون محتوای فایل‌ها (leak ممنوع)
     - هزینه: صفر تقریباً؛ فقط دستورات غیرقابل‌طبقه‌بندی می‌رسند
  5. manual mode فعلی
approval mining:
  comodor approvals suggest → از تصمیم‌های آدم‌تأیید过去 JSONL sessions:
  الگوهای تکرارشده (نرمال‌سازی path/flags) → پیشنهاد افزودن به allowlist پروژه
  با diff؛ هرگز کلاس‌های تخریبی/شبکه‌ای وسیع پیشنهاد نمی‌شود
  (کلاس‌بسته‌ها: rm به‌هرشکل، curl|sh، chmod 777، هر چیزی که به /etc و ~/.ssh
  و .env بنویسد، DROP/DELETE بدون WHERE)
deny globs کاربر: در safety.deny_patterns (گلوب روی دستور؛ روی نسخه‌های
  deobfuscated: حذف escape، تجزیه‌ی && و | و $() — هر شاخه جدا چک)
```

- **صادق بودن:** هر auto-approve توسط LLM در transcript برچسب بخورد («تأیید خودکار smart: <دلیل>») — قابل مرور در `/undo` و audit.
- خاموشی پیش‌فرض: smart off در v1؛ بعد از دو هفته داده، mining پیشنهاد می‌دهد.

## نقشه‌ی پیاده‌سازی

1. `safety/smart.py`: prompt + پارس پاسخ + timeout/fallback.
2. ادغام در `permissions.py` به‌عنوان لایه‌ی ۴ (ترتیب بالا).
3. `safety/mining.py`: استخراج الگو از sessions با نرمال‌سازی؛ CLI propose/apply.
4. deobfuscation مشترک (`expand &&, |, $( )`) — تست‌های نفوذ: `echo rm -rf / | sh` هرگز از پل نگذرد.
5. تست: blocklist مطلق حتی در smart و YOLO؛ timeout؛ mining قفل کلاس‌های تخریبی.

## پذیرش و تست

- دو هفته استفاده → `comodor approvals suggest` پیشنهادهای منطقی بدهد که با یک yes اعمال شوند.
- `rm -rf /` در هر مود (smart، YOLO، allowlist شده!) رد شود.
- auto-approve ها قابل مرور و قابل بازگشت (remove از allowlist).
- `comodor run --yes` (headless) با smart → همچنان deny برای نامعلوم‌ها.
