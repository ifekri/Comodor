# Spec: پرووایدرهای حافظه‌ی بیرونی (لایه‌ی اختیاری)

> **EN summary:** Hermes runs external memory backends (Honcho, Mem0, Supermemory, RetainDB, …) *alongside* built-in memory — at most one active — via a plugin abstraction. Comodor's brain is entirely local; some users will want cloud personalization or team-shared memory. This spec adds a minimal provider abstraction in `learning/providers/` where the built-in brain remains the primary and exactly one optional external provider mirrors writes and augments recall. Stdlib-first: the reference provider is plain HTTP; no SDK dependencies. Priority **P2** (valuable only after curated-memory ships), effort **M**.

## قابلیت در hermes چطور است

مرجع: `agent/memory_provider.py`، `plugins/memory/`.

- ۸ پرووایدر: Honcho (dialectic user modeling)، OpenViking، Mem0، Hindsight، Holographic، RetainDB، ByteRover، Supermemory.
- حداکثر یک پرووایدر فعال (دومین تلاش رد می‌شود — «جلوی schema bloat»).
- در کنار حافظه‌ی داخلی می‌دوند، هرگز جایگزینش نمی‌شوند؛ `notify_memory_tool_write` نوشته‌های داخلی را به بیرون mirror می‌کند (روی نوشته‌ی staged fail می‌کند).
- CLI: `hermes memory setup|status|off`.

## جای آن در Comodor

- موجود: `learning/store.py`، `mcp/http.py` (کلاس HTTP client با SSE — قابل reuse)، `config.py`.
- جدید: `learning/providers/base.py` (ABC کوچک) + `learning/providers/http_generic.py` (پرووایدر عمومی هر سرویس REST) و یک reference پیاده‌سازی برای یک سرویس واقعی (پیشنهاد: Mem0 — API ساده‌ی REST).

## طراحی پیشنهادی

```
کانفیگ: learning.provider.enabled=false,
        learning.provider.kind=http_generic,
        learning.provider.base_url=…, learning.provider.key_env=MEM0_API_KEY,
        learning.provider.mirror_writes=true, learning.provider.read_augment=false
ABC (٣ متد):
  mirror_write(fact)      # پس از هر نوشته‌ی داخلی موفق
  augment_recall(query) -> list[str]   # پیش از briefing، ادغام با سقف توکن
  status() -> str         # برای /doctor و /memory
قوانین سفت:
  - حافظه‌ی داخلی همیشه نویسنده‌ی اصلی است (source of truth)؛ بیرونی فقط mirror
  - حداکثر یک پرووایدر فعال؛ دومین = خطای پیکربندی روشن
  - augment فقط-افزودنی و با سقف ۴۰۰ توکن در briefing؛ شکست بیرونی هرگز جریان
    اصلی را نکند (log + ادامه — الگوی fail-openِ فقط برای افزونه‌ها، برخلاف گیت‌های امنیتی)
  - کلید فقط از env؛ هرگز در config.json (قانون mine_only)
```

- **تمایز تبلیغ‌شدنی:** در Comodor «cloud memory» هرگز اجباری یا پیش‌فرض نیست — برعکسِ برخی رقبا، حافظه‌ی محلی کامل است؛ بیرونی فقط یک دکمه.
- **شبکه و تحریم/حریم خصوصی:** فقط به base_url کاربر؛ بدون تلمتری؛ در `doctor.py` گزینه‌ی تست اتصال.

## نقشه‌ی پیاده‌سازی

1. `base.py` + `http_generic.py` (~۲۰۰ خط روی `net/http.py`).
2. قلاب‌ها: `learning/facts.py` پس از نوشته → `mirror_write`؛ `prompts.py` قبل از briefing → `augment_recall`.
3. `learning/provider commands` به `skills`-سبک CLI: `comodor memory-provider setup|status|off`.
4. تست: fake HTTP server (الگوی `tests/support/fake_mcp_server.py`)، قطع‌بودن شبکه، دو پرووایدر = رد.

## پذیرش و تست

- قطع کامل سرویس بیرونی → همه‌چیز مثل قبل کار کند، فقط log هشدار.
- فکت نوشته‌شده داخلی در سرویس بیرونی ظاهر شود (تست fake).
- هیچ کلیدی در دیسک؛ `doctor` آن را تأیید کند.
