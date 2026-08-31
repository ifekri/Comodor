# Spec: Credential Pool — چند کلید با چرخش خودکار

> **EN summary:** Comodor holds one API key per provider; a rate-limited or quota-exhausted key stalls the session. Hermes spreads API calls across multiple keys per provider with auto-rotation on rate limits (and subagents share the parent's pool, rotating instead of pinning). This spec adds a small pool layer in `providers/`: keys resolved as a list, round-robin start, rotate on 429/quota errors with cooldown tracking. Stdlib-only, ~300 lines. Priority **P1** (direct user pain for heavy users and teams), effort **S–M**.

## قابلیت در hermes چطور است

مرجع: `agent/credential_pool.py`، `agent/anthropic_credentials.py`.

- چند کلید به‌ازای پرووایدر؛ چرخش خودکار روی rate limit؛ فرزندها pool والد را share می‌کنند (چرخش به‌جای pin)؛ endpoint-scoped capability فقط با تطابق exact provider+base_url به ارث می‌رسد.

## جای آن در Comodor

- موجود: `providers/discover.py` (کشف کلیدهای env — نقطه‌ی طبیعی pool)، `providers/base.py`، `providers/openai_compat.py`/`anthropic.py` (گرفتن کلید تک)، `config.py` (قانون mine_only)، `providers/gateway.py` (health tracking — الگوی cooldown مشابه).
- جدید: `src/comodor/providers/pool.py`.

## طراحی پیشنهادی

```
منشأ کلیدها (ترتیب اتحاد):
  config.providers.<p>.api_keys: ["sk-1","sk-2"]   # لیست جدید؛ رشته‌ی منفرد = سازگار
  env: <P>_API_KEY (فعلی) + <P>_API_KEY_2..N
  هرگز هر دو لایه در فایل — mine_only مانع ذخیره‌ی env در دیسک
pool.py:
  next_key(provider) -> str
  report_rate_limited(provider, key, retry_after?)  # cooldown تا retry_after یا 60s
  report_ok(provider, key)                          # سلامت
  انتخاب: نوبتی از سالم‌ها؛ همه در cooldown → کمترین cooldown (با پیام روشن)
  برای subagent: اشتراک pool والد طبیعی است (process-داخلی)
آداپتورها: به‌جای key ثابت، از pool.next_key هر request؛ پاسخ 429/quota →
  report_rate_limited + یک retry با کلید بعدی (فقط قبل از اولین token استریم —
  قانون طلایی موجود gateway: بعد از شروع استریم هرگز retry نشود)
شفافیت: /cost و doctor فهرست کلیدها با ماسک (sk-1***…) و وضعیت (healthy/cooled)
حساب: usage per-key در brain.db meta تا کاربر ببیند کدام کلید کجا مصرف شد
```

- **تمایز با gateway موجود:** gateway بین *پرووایدرها* failover می‌کند؛ pool بین *کلیدهای* یک پرووایدر — دو لایه‌ی مستقل که با هم ترکیب می‌شوند.
- امنیت: کلیدها هرگز در log/transcript (redact.py از قبل)؛ ذخیره‌ی لیست در config فقط با اجازه‌ی mine_only (env-keys نمی‌آیند به دیسک).

## نقشه‌ی پیاده‌سازی

1. `providers/pool.py` — انتخاب/چرخش/cooldown/متادیتا.
2. `discover.py`: کشف چند env key.
3. ادغام در دو آداپتور + 429-handler (پیش از استریم).
4. UI: `/provider` گسترش — نمایش pool و سلامت.
5. تست: 429 → چرخش؛ همه در cooldown → پیام روشن؛ استریم‌شروع‌شده → هیچ retry؛ ماسک در هر خروجی.

## پذیرش و تست

- دو کلید و شبیه‌سازی 429 روی اولی → درخواست بعدی خودکار با دومی بدون دخالت.
- usage per-key در `/cost` دیده شود.
- هیچ کلید کامل در هیچ خروجی (تست redact).
