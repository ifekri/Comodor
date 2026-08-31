# Spec: پروفایل‌های همزمان

> **EN summary:** Comodor has a single `~/.comodor` home: one brain, one config, one skills folder, one set of channel daemons. Hermes's `hermes -p <name>` gives each profile its own home, config, memory, sessions, and gateway PID — profiles run concurrently (e.g., a "work" profile and a "personal" profile with separate Telegram bots and separate learning). This spec adds profiles by parameterizing `paths.py` with `COMODOR_PROFILE` / `--profile`, defaulting to `default` with zero behavior change for existing users. Priority **P2**, effort **S–M** (the architecture is already single-root; this is mostly threading a root variable).

## قابلیت در hermes چطور است

- `hermes -p name` → HERMES_HOME جدا، config، memory، sessions، gateway PID؛ پروفایل‌ها هم‌زمان می‌دوند؛ برای سرویس‌های multi-install هم نام سرویس پسوند می‌گیرد.

## جای آن در Comodor

- موجود: `paths.py` (کاربر root `~/.comodor` و پروژه root — نقطه‌ی واحد تغییر!)، `config.py`، `channels/unit.py` (نام سرویس per-profile)، `session/store.py`، `learning/store.py`، TUI/web (بدون آگاهی از پروفایل لازم).
- جدید: فقط گسترش `paths.py` + یک پرچم.

## طراحی پیشنهادی

```
فعال‌سازی:
  comodor --profile work …          # یا COMODOR_PROFILE=work
  پیش‌فرض «default» → ~-/.comodor (همان امروز؛ مهاجرت صفر)
ریشه‌ها:
  ~-/.comodor/profiles/work/        # brain.db، sessions، skills، media، cron…
  ~/.comodor/config.json            # پروفایل‌های پروفایل سهم سراسری: keys در env
  ~/.comodor/profiles/work/config.json
  (brain.db و هر چیزی per-profile؛ فقط catalogue محلی-مدل‌ها و مهارت‌های پایه
   می‌توانند سراسری بمانند — تصمیم: skills per-profile برای ایزوله‌ی یادگیری)
کانال‌ها: هر پروفایل daemon خودش؛ نام سرویس systemd/launchd با پسوند
  comodor-telegram@work.service (unit.py پسوند بگیرد)؛ دو پروفایل = دو bot token
  متفاوت (allowlist جدا) — طبیعی و امن
قفل‌ها: brain.db و cron tick per-profile؛ دو پروفایل هم‌زمان مشکلی ندارند چون
  هر نویسنده فایل‌های خودش
web/TUI: هدر پروفایل فعال نشان داده شود؛ اشتباه گرفتن دو پنجره جلوگیری شود
مهاجرت: در اولین اجرا با پروفایل‌ها، ~/.comodor فعلی → profiles/default (جابجایی
  به‌صورت move، با بکاپ؛ اگر شکست → هشدار و ادامه با ریشه‌ی قدیمی)
```

- **کاربردهای تبلیغ‌شدنی:** «دو شخصیت ایجنتی روی یک لپ‌تاپ» — کار و پروژه‌ی شخصی با مغز یادگیری جدا؛ کانال تلگرام شرکت جدا از شخصی؛ تست نسخه‌ی beta بدون خراب کردن مغز اصلی.
- **قید سادگی:** بدون پروفایل هیچ رفتاری عوض نشود؛ `--profile default` = binary همانی که امروز است (تست رگرسیون).

## نقشه‌ی پیاده‌سازی

1. `paths.py`: `profile_root()` + پرچم global؛ همه‌ی مسیرهای مشتق از root واحد.
2. `config.py`: بارگذاری لایه‌ی پروفایل بعد از لایه‌ی کاربر.
3. `channels/unit.py`: نام سرویس per-profile + daemon.
4. مهاجرت یک‌باره با بکاپ.
5. doctor: چک پروفایل فعال + فضا/سلامت هر پروفایل.
6. تست: هم‌زمانی دو پروفایل (تلگرام دو بات)، مهاجرت، رفتار پیش‌فرض unchanged.

## پذیرش و تست

- `comodor --profile work` با مغز خالی شروع شود، یادگیری مستقل انباشته شود؛ `default` دست‌نخورده.
- دو daemon کانال هم‌زمان روی دو پروفایل هر دو پیام بگیرند و جواب بدهند.
- یک نصب قدیمی بعد از آپدیت، بدون هیچ اقدامی دقیقاً مثل قبل کار کند.
