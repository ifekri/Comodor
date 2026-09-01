# Spec: صوت — TTS و STT

> **EN summary:** Comodor has zero audio capability. ابزار مرجع ships STT (whisper local, Groq, OpenAI) and TTS (Edge free, ElevenLabs, OpenAI, local NeuTTS) usable from CLI and chat channels, so the agent can talk back and take voice notes. This spec adds `src/comodor/voice/` with a provider-registry design mirroring `providers/`: STT default = local whisper.cpp via the existing llama.cpp-style process runner, TTS default = free Edge-TTS (HTTP, no key), both gated behind config and consumed by inbound-media (spec 02) and a future Discord voice mode. Priority **P1**, effort **M–L**.

## قابلیت در ابزار مرجع چطور است

- **STT:** پرووایدرهای `local` (whisper base/large-v3)، `groq` (whisper-large-v3)، `openai`؛ record key (push-to-talk) با silence detection، `submit_mode` (direct/draft).
- **TTS:** `edge` (رایگان، صوت‌های neural مایکروسافت)، `neutts` (محلی روی دستگاه)، `elevenlabs`، `openai`، `mistral`؛ `/voice on|off|tts|status`.
- Discord voice channel: join/leave + رونوشت به کانال متنی.
- نکته‌ی مستندشده: wake word ندارد — فقط push-to-talk.

## جای آن در Comodor

- موجود: `local/runtime.py` (راه‌اندازی سرور جدا-فرایند روی پورت loopback — الگوی عالی برای whisper.cpp سرور)، `local/download.py` (دانلود رزوم‌پذیر با sha256)، `providers/` (الگوی registry/adapter)، `net/http.py`، کانال‌ها (پیام صوتی خروجی Telegram voice message).
- جدید: `src/comodor/voice/` با `stt.py`، `tts.py`، `registry.py`، `commands.py` (`/voice`).

## طراحی پیشنهادی

```
کانفیگ:
  voice.enabled=false                 # همه‌چیز خاموش تا روشن شود
  voice.stt.provider=local            # local | groq | openai
  voice.stt.local.model=whisper-base  # catalogue با sha256 مثل local/models
  voice.stt.groq_key_env=GROQ_API_KEY
  voice.tts.provider=edge             # edge | openai | elevenlabs
  voice.tts.edge.voice=fa-IR-FaridNeural   # صوت فارسی پیش‌فرض وقتی locale=fa
  voice.tts.auto=false                # پاسخ‌ها خودکار صوتی شوند؟
API داخلی:
  voice.transcribe(wav_bytes) -> text
  voice.synthesize(text) -> mp3/opus bytes
```

- **STT محلی:** whisper.cpp به‌عنوان باینری پیش‌ساخته از طریق catalogue (`local/catalogue.py` الگو) با sha256 و بررسی RAM/دیسک قبل از دانلود — همان صداقت `local` موجود («اگر دستگاه نمی‌کشد، قبل دانلود بگو»). گزینه‌ی دیگر: فرستادن به Groq (API ساده، whisper-large-v3 ارزان) — پیش‌فرض `local`، چون آفلاین-پسند است.
- **TTS Edge:** HTTP عمومی مایکروسافت، بدون کلید، خروجی mp3 — سازگار با فلسفه‌ی «پیش‌فرض بدون کلید». کیفیت فارسی خوب (Farid/FaridNeural, DilaraNeural).
- **خروجی در کانال‌ها:** Telegram `sendVoice`، Discord/Slack فایل صوتی؛ در TUI فقط پخش محلی اگر player موجود (afplay/aplay) — بدون آن، مسیر فایل بگو.
- **ضبط TUI (v2):** push-to-talk همان record key با `sounddevice`؟ — نه: وابستگی می‌آورد. v1 = فقط STT/TTS فایل-محور و کانال‌ها؛ ضبط میکروفون TUI وقتی راه stdlib-only (arecord/sox/ffmpeg موجود) پیدا شود.
- محرمانگی: صوت ارسالی به پرووایدر ابری همیشه با اعلان در transcript ذخیره شود؛ پاک‌سازی فایل‌های صوتی موقت بعد از transcribe.

## نقشه‌ی پیاده‌سازی

1. `voice/registry.py` — الگوی `providers/registry.py`: پرووایدرها با `check_fn` (کلید/باینری موجود؟).
2. `stt.py` — آداپتور whisper.cpp-سرور (سرور HTTP whisper.cpp با `/inference`)؛ Groq/OpenAI از `net/http.py`.
3. `tts.py` — edge (endpoint HTTP + ssml)، openai، elevenlabs.
4. `voice/models.json` — catalogue باینری whisper.cpp per-OS با sha256 (الگوی `local/catalogue.py`).
5. اتصال: `inbound-media.md` → stt؛ `/voice` دستور TUI؛ خروجی کانال‌ها.
6. `doctor.py`: چک voice (باینری، کلید، پورت).
7. تست: transcribe فایل fixture کوچک؛ synthesize → mp3 معتبر؛ edge بدون کلید کار کند؛ provider ناموجود → خطای روشن.

## پذیرش و تست

- `/voice status` وضعیت صادقانه بگوید (کدام پرووایدر، کدام مدل، چه چیزی کم است).
- voice note تلگرام → متن درست (فارسی و انگلیسی) — پذیرش نهایی با فایل واقعی.
- TTS پاسخ فارسی در تلگرام به‌صورت voice message قابل پخش باشد.
- هرگز بدون `voice.enabled=true` هیچ صدایی دانلود/ارسال نشود.
