# Spec: Insights — آمار مصرف و هزینه

> **EN summary:** Comodor tracks cost per session (`/cost`) but has no cross-session view: which projects ate the budget, which model is the workhorse, is the learning brain actually improving (fewer corrections over time — `/progress` answers this but only within one session's episodes). ابزار مرجع ships `/insights` and `agent/insights.py` for token/cost/activity analytics plus per-model usage tables. This spec adds `comodor insights` — a pure-SQL aggregation over existing JSONL transcripts and brain.db meta, rendered in TUI and web. Zero new data collection; the data is already on disk. Priority **P1** (cheap, high perceived value), effort **S**.

## قابلیت در ابزار مرجع چطور است

مرجع: `agent/insights.py`، دستور `/insights [--days N]`، `agent/usage_pricing.py`، `agent/account_usage.py`.

- توکن/هزینه/فعالیت به تفکیک روز/مدل/پلتفرم؛ جدول‌های per-model usage؛ قیمت‌گذاری usage؛ گزارش‌گیری هرگز قیمت را از هوا نمی‌سازد (unknown = dash — Comodor همین قانون را دارد).

## جای آن در Comodor

- موجود: `session/store.py` (هر جلسه: model، provider، timestamps، message count، **cost** در metadata — داده آماده!)، `learning/store.py` (episodes، corrections — ماده‌ی «آیا بهتر می‌شوم»)، `learning/progress.py` (الگوی گزارش صادقانه + آستانه)، `ui/widgets` (الگوی داشبورد)، `web/session.py`.
- جدید: `src/comodor/insights.py` + دستور `/insights` + panel.

## طراحی پیشنهادی

```
دستور: /insights [days]   و   comodor insights [--days 30] [--json]
پنل (TUI widget + web):
  ── ۳۰ روز اخیر ─────────────────────────
  هزینه:      $12.40  (7 روز اخیر: $4.10 — روند ↑)
  جلسات:      63      پیام: 1,240
  برترین پروژه‌ها: comodor-alpha $5.20 · client-site $3.90 · scratch $1.10
  برترین مدل‌ها:   mimo-v2.5-pro 61% · claude-x 30% · local 9%
  بهبود مغز:    اصلاحات/۱۰ گام: 2.1 → 1.4 (در ۱۸ episode معتبر؛ آستانه رعایت شد)
  ذخیره‌ی cache:  82٪ hit (میانگین ۷ روزه)
  cron:        41 اجرا، 39 موفق، 1 incident باز
خروجی --json: همان داده‌ها برای اسکریپت‌ها
مبانی (فقط SQL):
  - هزینه: metadata جلسات (موجود) — بدون قیمت نامعلوم: dash، نه حدس
  - cache hit: از usage کالیبره‌شده‌ی agent/tokens.py (فیلد input_cached اگر
    پرووایدر بدهد — anthropic می‌دهد؛ ثبت در session meta از الان)
  - بهبود مغز: learning/progress.py روی کل episodes (نه فقط جلسه‌ی جاری)
حریم خصوصی: همه‌چیز محلی؛ هیچ تلمتری؛ export فقط با فرمان صریح
```

- **قاعده‌ی صداقت (borrow از progress.py):** زیر آستانه‌ی نمونه‌ی آماری، مقدار گزارش نشود — «نمونه‌ی کافی نیست»؛ روند‌ها هیچ‌وقت از ۲ نقطه ساخته نشوند.
- ثبت جدید لازم: `input_cached` و `cost` per message در JSONL (فیلد موجود cost را از پایان جلسه به per-message درآور تا insights دقیق باشد — تغییر کوچک سازگار).

## نقشه‌ی پیاده‌سازی

1. `session/store.py`: ثبت per-message usage/cost/cached (سازگار با فایل‌های قدیمی — فیلد غایب = skip).
2. `insights.py`: کوئری‌های تجمیعی JSONL (scan مسیر sessions؛ حجم سبک است).
3. widget TUI + `/insights` + web panel + `--json`.
4. تست: داده‌ی seed، آستانه‌ها، قیمت نامعلوم = dash، فایل‌های قدیمی.

## پذیرش و تست

- بعد از هفته‌ها استفاده، `/insights` بدون هیچ تنظیمی اعداد درست نشان دهد.
- پروژه با قیمت ناشناخته → dash نه عدد ساختگی.
- `/insights 7` روند ۷ روزه؛ زیر ۳ جلسه → «نمونه‌ی کافی نیست».
