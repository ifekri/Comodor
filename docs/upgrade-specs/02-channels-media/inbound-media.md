# Spec: رسانه‌ی ورودی در کانال‌ها (صوت‌نامه، عکس، فایل)

> **EN summary:** Today Comodor's three channels are text-only: a user cannot send a voice note, photo, or document from their phone. ابزار مرجع handles inbound media everywhere (voice transcription, vision on images, file reading). Closing this gap is the single biggest day-to-day usability win for phone-based use. This spec adds inbound media across Telegram/WhatsApp/Slack: download → type-detect → route (voice→STT via spec voice-tts-stt, image→vision via spec vision, text/file→read_file pipeline) with size caps, MIME pinning, and secrets-safe defaults. Priority **P0**, effort **M**.

## قابلیت در ابزار مرجع چطور است

- همه‌ی آداپتورها عکس/فایل/صوت را دریافت و به ابزار درون-ایجنتی تبدیل می‌کنند (`tools/audio_container.py`، `image_source.py`، `read_extract.py`).
- استریم‌های صوتی به STT، عکس‌ها به vision-capable مدل، PDF/دکی به extract متن.

## جای آن در Comodor

- موجود: کلاینت‌های API سه کانال (همه دانلود فایل دارند: `telegram/api.py getFile`، WhatsApp media endpoint، Slack `files.info`)، `net/http.py`، `agent/loop.py` (تزریق پیام چند-قطعه‌ای)، `providers/profile.py` (تشخیص پشتیبانی vision مدل).
- جدید: `src/comodor/media/` با `ingest.py` (تشخیص نوع + سقف‌ها)، `stt.py` (پل به spec صوت)، `extract.py` (متن از PDF/DOCX با پارس ساده؛ خارج از scope: OCR).

## طراحی پیشنهادی

```
کانفیگ: media.enabled=true, media.max_download_mb=25,
        media.voice_to_text=true, media.images_to_vision=true,
        media.save_dir="~/.comodor/media/<session>"  (پاک‌سازی ۷ روزه)
جریان:
  1. آداپتور پیام رسانه‌ای → دانلود به media.save_dir با نام هش‌شده
  2. ingest: MIME واقعی (magic bytes، نه extension) + سقف سایز
  3. مسیریابی:
     - audio/* → STT (spec voice-tts-stt) → متن به‌عنوان پیام کاربر با برچسب "[voice note]"
     - image/* → اگر مدل vision دارد: پیام چند-قطعه‌ای (text+image) به provider
                 اگر ندارد: پیام روشن «مدل فعلی عکس نمی‌فهمد»
     - text/code/pdf → خواندن با سقف توکن (الگوی read_file streaming) و خلاصه در پیام
  4. ذخیره‌ی مسیر فایل در transcript برای بازبینی؛ redaction روی فایل‌های .env و غیره
```

- **امنیت:** دانلود فقط به پوشه‌ی مدیریت‌شده؛ هرگز اجرای فایل ورودی؛ نام فایل sanitize؛ اگر پرووایدر image را نمی‌پذیرد، فایل حذف نشود بلکه مسیرش پیشنهاد شود (الگوی «انتقال نه حذف»).
- **Slack:** `files` event؛ **WhatsApp:** `messages[0].type` (audio/image/document) با دانلود signed URL؛ **Telegram:** `getFile` با bot token.
- هر کانال فیلد `media: {allowed_types, max_mb}` در کانفیگ خودش — پیش‌فرض: همه به‌جز ویدیو.

## نقشه‌ی پیاده‌سازی

1. `media/ingest.py` — magic-byte sniffing (جدول امضای ~۳۰ فرمت، stdlib)، سقف‌ها، sanitize.
2. آداپتورهای سه کانال: شناسایی پیام رسانه‌ای در event های موجود و فراخوانی ingest.
3. `providers/base.py`: نوع پیام `image_part` اضافه شود؛ adapter های anthropic/openai_compat آن را بفرستند (فرمت‌ها: base64 content block / image_url).
4. پل STT: اگر `voice-tts-stt` آماده نیست، پیام روشن «voice note received; transcription disabled».
5. تست: با فایل‌های واقعی کوچک در tests/fixtures — عکس، mp3، pdf، و «عکس جعلی» (extension jpg، محتوا exe) → رد.

## پذیرش و تست

- از تلگرام voice note بفرست → متن آن به‌عنوان درخواست پردازش شود.
- عکس اسکرین‌شات بفرست → مدل vision توضیح بدهد؛ با مدل غیر-vision → پیام روشن.
- فایل ۵۰ مگابایتی → رد با پیام سقف؛ فایل .env → redaction همان رویه‌ی `safety/redact.py`.
