# Spec: گراف یادگیری (/journey)

> **EN summary:** Hermes's learning graph (`/journey`) renders skills and memory chunks as nodes with edges from `related_skills` frontmatter and lexical-overlap links, feeding a desktop "constellation" visualization. Comodor has richer learning data (rules with evidence, lessons with score decay, associations, episodes) but no way to *see* it as a whole. This spec adds a `comodor journey` timeline + a lightweight TUI visualization built entirely from existing store data — no new analytics, just faithful rendering of what the brain already knows. Priority **P2** (after curated-memory and skill-lifecycle), effort **S–M**.

## قابلیت در hermes چطور است

مرجع: `agent/learning_graph.py`، `agent/learning_graph_render.py`، CLI `hermes journey`.

- نودها: مهارت‌های ساخته/استفاده‌شده (از usage) + هر chunk از MEMORY/USER (عنوان = خط اول ≤۸۰ کاراکتر، بدنه ≤۱۲۰۰).
- یال‌ها: `related_skills` در frontmatter (دوسویه، dedup) + پیوند واژگانی memory→skill (۴ مهارت برتر با overlap).
- خروجی برای پنل دسکتاپ + آمار (`edges_per_node`, `isolated_pct`, `memory_skill_edges`)؛ scrubber «صورت فلکی» قابل پخش در زمان.
- `hermes journey list|delete <node>|edit <node>` — node های حذف‌شدنی: مهارت آرشیو، chunk حذف.

## جای آن در Comodor

- Comodor از قبل داده‌ی بهتری دارد: `learning/store.py` جدول‌های `associations` (هم‌رخدادی واژه‌ها — یالِ آماده!)، `rules` (با evidence)، `lessons`/`facts` (با score و origin_episode)، `episodes` (خط زمان واقعی).
- جدید: `src/comodor/learning/journey.py` + `ui/widgets/journey.py` + CLI `comodor journey`.

## طراحی پیشنهادی

```
خروجی ۱ — خط زمان (بدون گراف):
  comodor journey / /journey در TUI
  لیست مرتب زمانی: هر ردیف = یک رویداد یادگیری:
  [تاریخ] lesson «همیشه از pytest استفاده کن» (score 0.8, 4 شواهد)
  [تاریخ] rule quotes.style (اکتساب از اصلاح کاربر در پروژه X)
  [تاریخ] skill «migrate-alembic» ساخته شد (origin: episode #42)
  [تاریخ] fact «DB = postgres 15»
خروجی ۲ — گراف واژگانی (v2):
  نود = lesson/fact/skill/rule؛ یال = جدول associations موجود + related_skills
  رندر در TUI با Rich (ماتریس مجاورت فشرده یا لیست همسایگی مرتب‌شده؛ گراف بوم‌دار
  فقط در web UI که HTML دارد)
آمار صادقانه (الگوی progress.py):
  isolated_pct، edges_per_node، و «برای این نود شاهدی وجود ندارد» — زیر آستانه
  نمونه، گزارش «unchanged» مثل progress
عملیات:  comodor journey delete <node> → همان قواعد curator (آرشیو نه حذف)
```

- **قید cache:** `/journey` فقط rendering است — هیچ داده‌ای به prompt تزریق نمی‌شود؛ prefix دست‌نخورده.
- حریم خصوصی: خروجی journey ممکن است شامل محتوای فکت‌های شخصی باشد — هرگز در export های خودکار نیاید.

## نقشه‌ی پیاده‌سازی

1. `learning/journey.py` — کوئری‌های خط زمان روی store (بدون LLM).
2. `ui/widgets/journey.py` — پنل TUI scrollable با رنگ theme.
3. آمار + قواعد آستانه (borrow از progress.py).
4. v2: گراف همسایگی‌ها از associations؛ در web UI SVG.
5. تست: خروجی بر داده‌ی seed شده؛ آستانه‌ی نمونه‌ی کم = پیام صادقانه.

## پذیرش و تست

- `/journey` پس از دو هفته استفاده، خط زمانی معنادار نشان دهد که کاربر بفهمد مغز چه یاد گرفته — «قابل مشاهده بودن یادگیری» خودش یک ویژگی رقابتی و تبلیغ‌شدنی است.
- هیچ رویدادی دوبار نیاید؛ حذف نود → همان معافیت‌های curator.
