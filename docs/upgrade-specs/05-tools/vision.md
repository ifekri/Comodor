# Spec: ابزار Vision (تحلیل تصویر کاربر)

> **EN summary:** Comodor can only take its own screenshots (desktop tool); a user cannot hand it an image to analyze. ابزار مرجع has a `vision` toolset that accepts pasted images/URLs and routes them to vision-capable models, with an auxiliary client for cheap side-calls. This spec builds on the inbound-media pipeline (spec 02) and `providers/profile.py` capability detection: a `vision` tool that accepts a local path/URL and returns a structured description, plus multi-part message support so users can attach images directly. Priority **P1**, effort **M**.

## قابلیت در ابزار مرجع چطور است

- toolset `vision`: تحلیل عکس از clipboard/URL/فایل با هر مدل vision-capable.
- `agent/auxiliary_client.py`: کارهای جانبی (vision، summarization) روی مدل ارزان جدا.
- image paste در CLI؛ OCR ضمنی از مدل.

## جای آن در Comodor

- موجود: `providers/profile.py` (vision flag per model — از قبل هست!)، `desktop/png.py`، `net/http.py`، media ingest (spec 02)، `tools/computer.py` (سقف توکن اسکرین‌شات — الگوی بودجه).
- لازم: پشتیبانی **پیام چند-قطعه‌ای** در `providers/base.py` + دو آداپتور (`anthropic.py`: content block image؛ `openai_compat.py`: image_url) — این زیرساخت مستقل از خود ابزار vision ارزش دارد.
- جدید: `src/comodor/tools/vision.py` + `src/comodor/vision.py` (دستیار encode/resize).

## طراحی پیشنهادی

```
ابزار:  vision(source: path|url, question?: str) — ریسک SAFE برای path داخل
        workspace/known؛ DANGEROUS برای URL (شبکه)
رسانه:  پیام کاربر با عکس (TUI paste با OSC 52/کلیپ‌بورد یا attach؛ کانال‌ها از
        spec inbound-media) → مستقیم در پیام چند-قطعه‌ای؛ بدون tool-call
مسیریابی مدل:
  - مدل جاری vision دارد → همان مدل
  - ندارد ولی مدل دیگری کانفیگ‌شده vision دارد → optional
    (vision.fallback_model، پیش‌فرض خاموش — صادقانه بگو «مدل X عکس را دید»)
  - هیچ → پیام روشن
بودجه: resize تا 1568px طول بزرگ‌تر (سقف آنتروپیک)، JPEG q=85 با png.py/
       zlib (encode دستی موجود) — سقف ~1MB؛ سقف ۴ عکس در هر پیام
امنیت: URL → همان گیت web_fetch؛ هرگز عکس user را به پرووایدر دیگری از
       کانفیگ کاربر نفرست؛ transcript نسخه‌ی ریزشده ذخیره کند نه base64 کامل
       (سقف دیسک JSONL — مسیر فایل + هش)
```

- **ادغام با computer:** اسکرین‌شات‌های `computer` همین مسیر چند-قطعه‌ای را بگیرند (تکرار فعلی حذف شود).
- OCR متن در عکس → همان خروجی مدل؛ ابزار OCR جدا لازم نیست.

## نقشه‌ی پیاده‌سازی

1. `providers/base.py`: نوع part تصویر + mape در دو آداپتور (با تست wire فرمت واقعی).
2. `vision.py`: دانلود/خواندن، resize با zlib+jpeg ساده یا pass-through؛ اگر JPEG encode دستی سنگین شد، PNG فقط-resize با zlib موجود.
3. `tools/vision.py` + advertised اگر مدل vision دارد (check_fn از profile).
4. TUI: paste image (کلیپ‌بورد) → attach موجود گسترش یابد.
5. تست: عکس fixture، مدل fake با پاسخ اسکریپت‌شده، بودجه، transcript سبک.

## پذیرش و تست

- paste یک عکس دیاگرام در TUI و پرسیدن «این چه می‌گوید» → پاسخ درست.
- مدل بدون vision → پیام روشن + گزینه fallback اگر کانفیگ شده.
- جلسه‌ی ۵۰ عکسی → JSONL متورم نشود (هش + فایل بیرونی).
