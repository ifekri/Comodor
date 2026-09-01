# Spec: ارجاع‌های زمینه با @ (فایل/پوشه/diff/git/url)

> **EN summary:** ابزار مرجع's `@` references inline-inject content into a message before it reaches the model: `@file:path[:10-25]` (line ranges), `@folder:` (tree, capped), `@diff`/`@staged`, `@git:N` (last N commits with patches), `@url:` — with tab completion, soft/hard budget limits (25% warn / 50% refuse), and credential-path blocking. Comodor only has file attach (Ctrl-O). This spec adds `@` parsing to the TUI prompt editor — the natural next step, and one of the most-copied UX ideas in modern CLI agents. Priority **P1**, effort **M**.

## قابلیت در ابزار مرجع چطور است

مرجع: `agent/context_references.py`.

- فرم‌ها: `@file:path[:10-25]` (بازه‌ی سطری ۱-مبنا)، `@folder:path` (درخت با سقف ۲۰۰ فایل)، `@diff`، `@staged`، `@git:N` (حداکثر ۱۰ commit با پچ)، `@url:https://…`.
- بسط زیر `--- Attached Context ---` قبل از رسیدن به ایجنتی؛ tab-completion؛ سقف نرم ۲۵٪ context (هشدار) و سخت ۵۰٪ (رد).
- **بلاک مسیرهای اعتباری:** `~/.ssh/`، `~/.aws/`، `~/.gnupg/`، `~/.kube/`، shell profiles، `.netrc`، `.env*`، هاب مهارت‌ها؛ محصوریت workspace؛ رد باینری.
- فقط CLI — روی پیام‌رسانی‌ها بسط داده نمی‌شود.

## جای آن در Comodor

- موجود: `ui/input/` (پارسر ورودی خام، bracketed paste — نقطه‌ی تعامل `@`)، `tools/attach`/clipboard (`Ctrl-O` موجود)، `safety/redact.py`، `agent/context.py` (بودجه‌ی توکن و سقف‌ها — همان مبنای ۲۵/۵۰٪)، `tools/browse.py` (برای @url — reuse)، git از طریق run_shell در بسط‌دهنده (خارج از ایجنتی).
- جدید: `src/comodor/context_refs.py` (پارسر + بسط‌دهنده) + ادغام در `ui/app.py`.

## طراحی پیشنهادی

```
فرم‌ها (v1): @file:path[:10-25] · @folder:path · @diff · @staged · @git:N · @url:…
بسط: در TUI قبل از ارسال turn؛ متن بسط‌یافته زیر «--- زمینه پیوست ---» به پیام
     کاربر اضافه شود (در transcript هم ثبت شود — شفافیت)
بودجه: نرم ۲۵٪ context → هشدار inline در editor؛ سخت ۵۰٪ → رد ارسال با شمارش
tab completion: مسیرها از list_dir محلی؛ کمبوی سبک در editor موجود
امنیت (همان فهرست ابزار مرجع + اضافه‌های Comodor):
  - ~/.comodor/config.json و brain.db هرگز با @ خوانده نشوند (کلیدها/آموزه‌ها)
  - redaction روی محتوای بسط‌یافته قبل از ارسال (الگوی redact.py)
  - باینری → رد با سایز؛ فایل بزرگ → سقف و اشاره به read_file
کانال‌ها: v1 فقط TUI؛ v2 همان پارسر برای پیام‌های کانال (این‌جا هم کاربرد دارد:
  «@file:config/settings.py» از تلگرام)
```

- **هم‌افزایی با ابزارها:** @ بسطِ *پیش از مدل* است؛ تکمیلش `read_file` است نه جایگزینش — پیام راهنما وقتی کاربر @ بزرگ می‌کشد: «بهتر است از read_file بپرسی؟» (الگوی claims.py — صداقت درباره‌ی مصرف).
- **فقط TUI بسط می‌دهد:** در حالت headless `run`، @ها هم بسط یابند (سود برای cron: prompt های cron بتوانند @diff داشته باشند) — با همان سقف‌ها.

## نقشه‌ی پیاده‌سازی

1. `context_refs.py` — tokenizer (@file/@folder/@diff/@staged/@git/@url) + بسط با سقف‌ها + بلاک‌لیست.
2. ادغام `ui/app.py`: تشخیص @ در editor، hint، completion.
3. گزارش مصرف بسط در پیش‌نمایش turn (sidebar context gauge موجود به‌روز شود).
4. تست: بازه‌ی سطری، بلاک‌لیست (.env, ~/.ssh, config.json)، بودجه‌ی ۵۰٪، باینری، url غیر http رد.

## پذیرش و تست

- «@diff این تغییر را توضیح بده» در یک turn کار کند بدون هیچ tool-call.
- @file:~/.ssh/config → رد با پیام امنیتی.
- بسط بزرگ‌تر از ۵۰٪ → رد ارسال؛ ۳۰٪ → هشدار مرئی.
- در transcript، متن بسط‌یافته قابل مرور باشد (شفافیت).
