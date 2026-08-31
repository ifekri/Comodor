# Spec: تولید تصویر

> **EN summary:** ابزار مرجع offers text-to-image via multiple providers (FAL, OpenAI images, …) behind an `image_gen` toolset with a registry abstraction. For Comodor this is a P2 nice-to-have — useful for marketing/docs assets and channel content, but far from the core coding loop. The spec keeps it deliberately small: one `image_gen` tool over a registry, stdlib HTTP only, key-from-env, images saved into the session media dir with explicit provenance. Priority **P2**, effort **S–M**.

## قابلیت در ابزار مرجع چطور است

مرجع: `agent/image_gen_provider.py`، `agent/image_gen_registry.py`، `tools/image_generation_tool.py`، `agent/image_routing.py`.

- ~۱۱ مدل از FAL (FLUX خانواده، GPT-Image، Nano Banana Pro، Ideogram) + پرووایدرهای دیگر؛ routing با انتخاب مدل؛ Nous Portal bundle.

## جای آن در Comodor

- موجود: `net/http.py`، `media/` (spec inbound-media — پوشه‌ی ذخیره و پاک‌سازی)، الگوی registry از `providers/`.
- جدید: `src/comodor/imag_gen/` (توجه: نام `image_gen`) با `registry.py` + آداپتورها.

## طراحی پیشنهادی

```
ابزار:  image_gen(prompt, model?, size?, output_path?) — ریسک DANGEROUS (هزینه‌ی
        پولی هر call — همان منطق هزینه که run_shell دارد؛ هر فراخوانی در /cost
        با قیمت تخمینی گزارش شود)
پرووایدرها (v1): openai (images API) + هر endpoint سازگار-OpenAI (incl. local
        image servers) — فقط HTTP؛ FAL اگر demand آمد
کانفیگ: image_gen.enabled=false (پیش‌فرض خاموش — هزینه‌ساز),
        image_gen.provider=openai, image_gen.model=gpt-image-1,
        image_gen.key_env=OPENAI_API_KEY, image_gen.max_per_day=10
ذخیره:  ~/.comodor/media/generated/<session>/… با provenance در transcript
        (prompt + model + timestamp)؛ redaction قبل از ارسال به پرووایدر نه ممکن
        است — پس هشدار: prompt حاوی کد/سکریت، خارج-شدن محتوا = آگاهانه
کانال‌ها: خروجی مستقیم به کانال مبدأ (تلگرام sendPhoto) وقتی از کانال آمده
```

- **چرا این spec کوچک است:** برخلاف ابزار مرجع (که ۱۱ مدل و routing دارد)، یک پرووایدر + یک مدل پیش‌فرض کافی است؛ تفاوت‌گذاری رقابتی Comodor این نیست — این فقط «پارتی کست کامل بودن» است. اگر روزی اولویت شد، فقط آداپتور اضافه می‌شود (registry آماده).
- **گیت بودجه:** `max_per_day` شمارنده در brain.db meta؛ رد شدن با پیام روشن.

## نقشه‌ی پیاده‌سازی

1. `image_gen/registry.py` (الگوی providers) + آداپتور openai.
2. ابزار + accounting هزینه در `/cost` موجود.
3. ذخیره + provenance + پاک‌سازی دوره‌ای (media).
4. تست: fake HTTP provider، سقف روزانه، prompt طولانی، خروجی به کانال.

## پذیرش و تست

- بدون `image_gen.enabled=true` ابزار اصلاً advertise نشود.
- هر تولید، در `/cost` دیده شود؛ بیش از سقف → رد روشن.
- عکس تولیدی از تلگرام قابل دریافت باشد.
