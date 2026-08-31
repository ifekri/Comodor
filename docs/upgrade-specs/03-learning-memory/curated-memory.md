# Spec: حافظه‌ی منتخب با review پس‌زمینه‌ای

> **EN summary:** Comodor's learning brain captures *corrections and rules* (declarative, evidence-backed) but has no free-form *facts* store: «پروژه‌ی X با Postgres 15 کار می‌کند»، «کاربر ساعت‌هاش Europe/Tehran است»، «کانال تلگرام فقط برای اعلان است». Hermes maintains two small curated files (MEMORY.md ~2,200 chars env-facts, USER.md ~1,375 chars user-profile) written by a *background review* agent that replays each turn forked off the hot path, with frozen-at-session-start injection to protect the prefix cache. This spec adds a `facts` table to the existing `brain.db` plus a background review pass — deliberately injected into the user message (briefing), not the system prompt, preserving Comodor's cache invariant. Priority **P0**, effort **L**.

## قابلیت در hermes چطور است

مرجع: `agent/memory_manager.py`، `agent/background_review.py`.

- **دو فایل با سقف کاراکتر** (MEMORY 2,200 ≈ ۸۰۰ توکن؛ USER 1,375 ≈ ۵۰۰) با جداکننده‌ی `§`؛ سرصفحه درصد مصرف («۶۷٪ — ۱,۴۷۴/۲,۲۰۰»).
- تزریق **snapshot منجمد در شروع جلسه** — تغییرات فقط جلسه‌ی بعد اعمال می‌شوند؛ cache نمی‌شکند.
- ابزار `memory` با اکشن‌های add/replace/remove (match زیر-رشته‌ای، مبهم = خطا)؛ ورود تکراری = موفق بی‌تغییر؛ سقف = خطا با فهرست ورودی‌ها برای ادغام.
- **background review:** نخ daemon بعد از هر turn، یک `AIAgent` fork با همان پرووایدر/credentials/system prompt کش‌شده (cache گرم) و whitelist محدود به ابزارهای memory/skill؛ turn زنده‌ی جدید review در-flight را کنسل می‌کند؛ هرگز جلوی turn کاربر را نمی‌گیرد؛ مصرف جداگانه در `task='background_review'`؛ مدل ارزان‌تر = کاهش ۳–۵ برابری هزینه.
- اسکن امنیتی ورودی‌ها (prompt injection، credential، invisible unicode) قبل از پذیرش.
- write approval اختیاری: `[auto]` staging با `/memory pending|approve|reject`.

## جای آن در Comodor

- موجود: `learning/store.py` (SQLite+FTS5 با جدول‌های lessons/skills/episodes/feedback/rules/signals)، `learning/reflect.py` (الگوی فراخوانی LLM پس‌زمینه‌ای — background review همان نهاد است با هدف متفاوت)، `learning/writer.py` (نویسنده‌ی async بچ)، `prompts.py` (briefing injection)، `safety/redact.py`.
- **تفاوت طراحی عمدی:** حافظه‌ی hermes فایل‌md با سقف کاراکتر است؛ در Comodor **جدول `facts` در brain.db** با همین سقف‌ها (چون سقف‌ها خوب‌اند: خوانا، cache-cheap، محدودکننده‌ی بی‌انضباطی) ولی با مزیت‌های DB: نسخه‌بندی، شواهد (episode_id مبدأ)، score/decay، و scope پروژه/سراسری.
- **تزریق:** در briefingِ پیام کاربر (نه system prompt) — همان مسیر rules؛ بخش «حافظه‌ی منتخب» با سقف جدا (۸۰۰+۵۰۰ توکن) از `hotindex.py` خوانده شود.

## طراحی پیشنهادی

```
جدول facts: {id, scope: project|global, kind: memory|user, text, origin_episode,
             created_at, updated_at, score, pinned}
سقف‌ها: memory 8 فکت ~100 کاراکتر، user 6 فکت — با نمایش «مصرف ۷۵٪» به ایجنتی
ابزار:  memory(action: add|replace|remove|list, kind, text)
        → ریسک SAFE؛ سقف = خطا با فهرست فعلی و اصرار به replace/remove
review پس‌زمینه‌ای:
  بعد از هر turn کامل (نه وسط استریم)، با مدل کمکی ارزان (پیش‌فرض: همان مدل؛
  کانفیگ learning.review.model برای مدل ارزان‌تر):
  "از این گفتگو حقیقت ماندگار (نه محتوای ترنزیشنی) استخراج کن؛
   اگر هیچ، دقیقاً NOTHING برگردان" — الگوی reflect.py که به «هیچ» متمایل است
  هرگز وسط turn کاربر نگذرد؛ turn جدید آن را کنسل کند
تأیید:  learning.review.write_approval=false پیش‌فرض؛ true → staging در facts با
        status=staged و تأیید با /memory pending|approve (الگوی skills/propose.py —
        چیز مهم هرگز بدون آدم‌تأیید نوشته نمی‌شود)
امنیت:  هر فکت پیش از پذیرش با redact.py چک شود؛ متن با کلید/توکن → رد
```

- **ادغام با مغز موجود:** فکت‌ها و rules دو لایه‌ی یک brain باشند؛ `/memory` در TUI مرورگر موجود (`widgets/memory browser`) گسترش یابد؛ `/progress` موجود شمارش فکت‌های ثابت‌شده را هم گزارش کند.
- **کنسل-در-برخورد:** الگوی hermes «review جدید کنسل‌کننده‌ی قبلی» ساده و درست است — فقط آخرین review اجرا شود.

## نقشه‌ی پیاده‌سازی

1. schema migration در `learning/store.py` (جدول facts + index scope/kind).
2. `learning/facts.py` — منطق سقف/تکرار/replace با پیام‌های راهنما (الگوی خطاهای `tools/registry.py`).
3. `agent/memory_tool.py` — ابزار `memory` با ریسک SAFE.
4. `learning/review.py` — نخ پس‌زمینه‌ای؛ prompt مستقر روی «NOTHING برگردان»؛ مصرف توکن در accounting جدا.
5. تزریق briefing: فصل «حافظه‌ی منتخب» در `prompts.py` (بعد از rules) — فقط از snapshot شروع جلسه.
6. `/memory` دستور TUI + web panel.
7. تست: سقف، تکرار، staging، کنسل در برخورد، injection attack (فکت با «ignore previous instructions» باید در خروجی بی‌اثر و قابل‌مشاهده باشد).

## پذیرش و تست

- در یک جلسه بگویی «DB این پروژه postgres است» → جلسه‌ی بعد ایجنتی بداند، بدون اینکه system prompt تغییر کرده باشد (تست prefix-hash ثابت).
- هیچ فکتی بدون یا user-approval یا threshold اطمینان نوشته نشود (برخلاف hermes که پیش‌فرض auto است — Comodor محافظه‌کارتر بماند؛ این تفاوت تبلیغ‌شدنی است).
- مصرف هزینه‌ی review در `/cost` دیده شود و قابل خاموش‌شدن باشد.
