# Spec: SSRF Guard — سپر درخواست‌های خروجی

> **EN summary:** Comodor's `web_fetch` and `browse` (CDP) can currently be steered toward internal addresses — cloud metadata endpoints (169.254.169.254), localhost services (Docker daemon, internal admin panels), or redirect chains that hop back inside. ابزار مرجع runs an always-on SSRF guard across every URL-fetching tool: RFC1918/loopback/link-local/CGNAT blocked, cloud-metadata hostnames blocked, fail-closed on DNS failure, per-hop redirect revalidation. This is one of the cheapest high-value specs in this folder: pure stdlib, ~200 lines, protects anyone running Comodor on a cloud VM (which the cron + channels features actively encourage). Priority **P1**, effort **S**.

## قابلیت در ابزار مرجع چطور است

- SSRF guard همیشه-روشن روی همه‌ی ابزارهای URL: بلاک RFC1918، loopback، link-local (شامل 169.254.169.254)، CGNAT، hostname های metadata ابری (metadata.google.internal و…)؛ DNS fail = رد؛ در هر hop ریدایرکت دوباره‌اعتبارسنجی؛ blocklist کاربر روی همه‌ی URL tools.

## جای آن در Comodor

- موجود: `net/http.py` (نقطه‌ی تزریق واحد — همه‌ی HTTP از اینجا می‌گذرد)، `tools/web.py` (web_fetch/web_search)، `browser/launch.py` + `browser/page.py` (CDP — ناوبری صفحه‌ها)، `tools/browse.py`.
- جدید: `src/comodor/safety/ssrf.py`.

## طراحی پیشنهادی

```
safety/ssrf.py — دو تابع خالص:
  assert_url_safe(url)     # پیش از اتصال: scheme فقط http/https؛ hostname
                           # literal-IP یا رزولوشن → چک آدرس:
                           #   رد: loopback, RFC1918, link-local(169.254), CGNAT,
                           #   0.0.0.0, ULA fe80::/10..., IPv6 مخصوص (fe80, fc00)
                           #   رد: hostname های metadata (metadata.google.internal,
                           #   metadata.azure.com, 169.254.169.254 هر alias)
                           # DNS failure = رد (fail-closed)
  assert_redirect_safe(from_url, to_url)  # در هر hop (http.py redirect handler)
اتصال:
  - net/http.py: در connection و در redirect handler (per-hop)
  - tools/web.py و tools/browse.py: assert قبل از ارسال؛ خطا = پیام روشن
    «آدرس داخلی — اجازه‌ی دسترسی نیست»
  - browser CDP: ناوبری Page.navigate قبل‌از-فرمان چک؛ ریدایرکت‌های درون مرورگر
    با Page.frameNavigated event پایش و اگر داخل‌رفت → قطع + گزارش
استثناها (چون Comodor خودش loopback سرور دارد):
  - کانفیگ safety.ssrf.allow_loopback=false پیش‌فرض؛ برای اعتماد به localhost
    کاربر (مثلاً dev server خودش) true per-project
  - allowlist صریح: safety.ssrf.allowlist=["http://localhost:3000/*"]
  - قواعد هرگز برای کلاینت‌های خود Comodor (providers API) اعمال نشوند — فقط
    مسیر ابزارهای مدل
blocklist کاربر: safety.url_blocklist (گلوب) روی همه
```

- نکته‌ی مهم: فقط مسیر **مدل** گیت شود — کانال‌ها/پرووایدرهای خود برنامه از `net/http.py` با فلگ skip عبور کنند تا ارائه‌ی سرویس نشکند.
- IPv6 و DNS rebinding: رزولوشن واقعی و چک آدرس رزولوشن‌شده (نه فقط hostname) — rebinding پایه‌ای پوشش داده می‌شود؛ TTL-race کامل خارج از scope و در docs گفته شود.

## نقشه‌ی پیاده‌سازی

1. `safety/ssrf.py` با جدول‌های CIDR (stdlib ipaddress) — ~۲۰۰ خط.
2. اتصال http.py + دو ابزار + CDP.
3. فلگ skip برای مسیرهای داخلی برنامه.
4. تست: metadata IP، ریدایرکت بیرون→درون، DNS fail، localhost allowlist، rebinding پایه.

## پذیرش و تست

- `web_fetch http://169.254.169.254/latest/meta-data/` → رد روشن.
- ریدایرکت از URL بیرونی به `http://127.0.0.1:8500` → رد در hop دوم.
- `browse http://localhost:3000` با allowlist پروژه → کار کند.
- ارائه‌ها (پرووایدرها، تلگرام) با guard فعال هم‌چنان کار کنند.
