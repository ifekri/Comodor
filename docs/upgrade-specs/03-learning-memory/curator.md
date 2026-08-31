# Spec: Curator — نگهداری دوره‌ای مغز و مهارت‌ها

> **EN summary:** Hermes's curator is an idle-triggered maintenance pass: deterministic auto-transitions (stale at 30d, archived at 90d, pinned and cron-referenced skills exempt), optional LLM consolidation (merge narrow skills into broader umbrella skills), content-addressed backups with rollback, and per-mutation audit. As Comodor accumulates lessons, rules, facts, and skills across projects, the same hygiene problem arrives. This spec adds a `comodor curator` pass over `brain.db` + `skills/` reusing the decay/score machinery that already exists — Comodor's half-life decay makes parts of this *easier* than Hermes. Priority **P1**, effort **M**.

## قابلیت در hermes چطور است

مرجع: `agent/curator.py`، CLI `hermes curator`.

- تریگر: بیکاری ≥۲ ساعت؛ فاصله‌ی پیش‌فرض ۱۶۸ ساعت؛ اجرا با مدل کمکی fork‌شده.
- فاز ۱ قطعی: stale در ۳۰ روز، archived در ۹۰ روز؛ pinned ها و مهارت‌های referشده توسط cron معاف؛ مهارت‌های never-used با grace؛ آرشیو = «ماکسیمم تخریب» به `~/.hermes/skills/.archive/`.
- فاز ۲ (opt-in، پیش‌فرض خاموش — توکن می‌خورد): consolidation با LLM — چترسازی، ادغام مهارت‌های narrow در broad با references/؛ rewrite ارجاع‌های cron.
- state در `.curator_state` + گزارش `REPORT.md`؛ `backup|rollback --list|--id|pause/resume|pin/unpin|prune_builtins`.
- **learning graph** هم از همین داده‌ها ساخته می‌شود (spec جدا: learning-graph.md).

## جای آن در Comodor

- موجود و مطلوب: `learning/store.py` (decay نیم‌عمر ۴۵ روزه و score از قبل محاسبه می‌شوند — curator فقط **عمل** می‌زند)، `learning/progress.py` (الگوی «گزارش صادقانه؛ بدون روند کافی گزارش نده»)، `skills/usage.py` (spec skill-lifecycle)، `learning/reflect.py` (مدل کمکی).
- جدید: `src/comodor/learning/curator.py` + CLI `comodor curator`.

## طراحی پیشنهادی

```
تریگر: پس از پایان جلسه اگر (فاصله از آخرین pass > curator.interval_days، پیش‌فرض ۷)
       و سیستم بیکار؛ هرگز وسط جلسه
فاز ۱ (قطعی، توکن-صفر):
  - lessons با score < floor و pin=false → وضعیت stale (نمایش نمی‌شوند ولی حذف نمی‌شوند)
  - فکت‌های تکراری/زیرمجموعه‌ای (match متن) → ادغام با ثبت origin هر دو
  - مهارت‌ها: استفاده‌نشدن در ۳۰ روز → stale؛ ۹۰ روز → archive به .archive/
    معافیت: pinned، referشده در cron jobs (spec 01)، ایجاده‌شده توسط کاربر
فاز ۲ (opt-in، learning.curator.consolidate=false پیش‌فرض):
  ادغام مهارت‌های هم‌خانواده با یک فراخوانی مدل کمکی؛ هر پیشنهاد = proposal
  با diff (هرگز خودکار اعمال) — الگوی propose.py
پشتیبان: قبل از هر عمل، محتوای قبلی به بلاک sha256 (الگوی ledger مهارت‌ها)
گزارش: ~/.comodor/logs/curator/REPORT.md — جدول انتقال‌ها با دلیل؛ و در TUI
  خلاصه‌ی یک‌خطی: «Curator: 3 lesson stale، 1 skill archived — /curator برای جزئیات»
CLI:    comodor curator run|report|rollback --id|pause|resume|pin <skill>|unpin
کانفیگ: learning.curator.interval_days=7, learning.curator.consolidate=false,
        learning.curator.stale_days=30, learning.curator.archive_days=90
```

- **تفاوت با decay موجود:** decay فقط score را پایین می‌آورد (passive)؛ curator تصمیم وضعیتی می‌گیرد (active) و گزارش می‌دهد. هر دو لازم‌اند و مکمل هم.
- عدم رونویسی: هیچ‌چیز hard-delete نمی‌شود مگر با فرمان کاربر؛ archive بازگشت‌پذیر.

## نقشه‌ی پیاده‌سازی

1. `learning/curator.py` فاز ۱ (SQL خالص روی store) + گزارش.
2. بکاپ بلاک‌ها (reuse ledger مهارت‌ها).
3. تریگر پس‌از-جلسه در `agent/loop.py`/`session/store.py`.
4. فاز ۲ با مدل کمکی + proposal flow.
5. CLI + `/curator` خلاصه در TUI.
6. تست: معافیت‌ها، rollback، مهارت referشده در cron آرشیو نشود.

## پذیرش و تست

- پس از یک ماه استفاده‌ی واقعی، `/progress` و گزارش curator نشان دهند مغز در حال کوچک/خوانا ماندن است، نه انباشت بی‌پایان.
- pin یک lesson → هرگز stale نشود.
- consolidate خاموش پیش‌فرض؛ روشن‌کردن هرگز بدون proposal چیزی را عوض نکند.
