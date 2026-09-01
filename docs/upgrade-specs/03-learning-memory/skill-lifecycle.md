# Spec: lifecycle خودبهبود مهارت‌ها (ساخت/پچ/linter/usage/ledger)

> **EN summary:** Comodor can only *propose* a SKILL.md for user approval (`skills/propose.py`); once created, skills never change. ابزار مرجع closes a full loop: the agent autonomously creates skills after successful multi-step workflows, patches them with fuzzy find-and-replace (with self-correction on ambiguity), a linter validates quality, a usage sidecar tracks use/view/patch counts, and a content-addressed ledger makes every mutation undoable. This spec upgrades `skills/` with: skill_manage tool (create/patch/edit/delete), a quality linter, usage telemetry, and an append-only ledger with sha256 blob backups — keeping human approval as the default, since that is a Comodor differentiator. Priority **P0**, effort **L**.

## قابلیت در ابزار مرجع چطور است

مرجع: `tools/skill_manager_tool.py`، `tools/skill_linter.py`، `tools/skill_usage.py`، `tools/skill_ledger.py`، `agent/skill_preprocessing.py`.

- **skill_manage:** create/patch (پچ فازی توکن-کارآمد؛ unique-match الزامی؛ شکست = preview فایل برای self-correction)/edit/delete/write_file/remove_file؛ batch `operations` اتمیک با rollback per-skill.
- ساخت خودکار مشوق دارد: «بعد از موفقیت چند-گامی، بازیابی خطا، یا اصلاح کاربر → روال را به‌صورت مهارت ثبت کن»؛ فرمت SKILL.md با قید «۵۷ کاراکتر اول description = تریگر خودکفا» (به‌خاطر truncate در index).
- **linter** (یافته‌های ERROR/WARNING مشورتی): ارجاع ابزار shell به‌جای نام ابزار native، متادیتای missing، ناهمخوانی name/دایرکتوری، لینک references شکسته، کلمات بازاریابی، فایل‌های scaffold ممنوع (README، CHANGELOG، .env).
- **usage sidecar** (`.usage.json` کنار مهارت‌ها): created_by/use_count/view_count/patch_count/state/pinned؛ نوشتن اتمیک + قفل بین-فرایندی.
- **ledger** (`.curator_ledger.jsonl`): هر mutation با actor و before/after + بلاک‌های sha256 در پوشه‌ی backups؛ «telemetry, not a gate» — شکست ledger هرگز جلوی کار را نمی‌گیرد؛ rollback دستی ممکن.
- سقف ~۱۰۰k کاراکتر؛ write approval اختیاری (`/skills pending|diff|approve`).

## جای آن در Comodor

- موجود: `skills/loader.py` (فرمت Agent Skills)، `skills/registry.py` (matching BM25)، `skills/propose.py` (پیشنهاد→تأیید)، `skills/commands.py`، `learning/store.py` (برای ترویج رویه‌های اثبات‌شده)، `safety/checkpoints.py` (الگوی content-addressed).
- جدید: `src/comodor/tools/skill_manage.py`، `src/comodor/skills/linter.py`، `src/comodor/skills/usage.py`، `src/comodor/skills/ledger.py`.

## طراحی پیشنهادی

```
ابزار:  skill_manage(action, name, …) — ریسک WRITE (پوشه‌ی مهارت‌ها؛ خارج workspace
        تعریف جدیدی از مجوز لازم دارد: مسیرهای مجاز = ~/.comodor/skills و .comodor/skills)
linter: یافته‌های مشورتی بعد از هر mutation در نتیجه‌ی ابزار (نه جدا)؛ یافته‌ی ERROR
        فقط هشدار است، هرگز blocker (فلسفه‌ی «telemetry not a gate» حفظ شود)
usage:  ~/.comodor/skills/.usage.json — همان شمای ابزار مرجع؛ شمارش view از registry
ledger: ~/.comodor/skills/.ledger.jsonl + بلاک‌های sha256 در ~/.comodor/.skills-backup/
        CLI: comodor skills rollback --list|--id
تأیید انسانی (تفاوت عمدی با ابزار مرجع):
  پیش‌فرض learning.skills.auto_create=false → هر create/patch فقط پیشنهاد
  (skill proposal موجود با diff کامل — الگوی propose.py)
  true → create خودکار ولی پچ‌های بعدی باز هم «پیشنهاد-با-diff» در turn بعد
  (این «خودبهبود آهسته» همان حلقه‌ی ابزار مرجع را می‌بندد ولی هرگز بی‌اجازه مغز نمی‌بافد)
پچ:     تطبیق دقیق → line-ending → whitespace → indentation
        (همان نردبان ثابت‌شده‌ی tools/matching.py — reuse مستقیم!)
```

- **اتصال به مغز:** وقتی `skills/propose.py` رویه‌ای با score بالا را ترویج می‌کند، همان مسیر skill_manage(create, draft) طی شود؛ ledger actor="brain" بگیرد.
- **امنیت:** اسکن هر مهارت جدید با همان چک‌های ابزار مرجع (prompt injection، command خطرناک، exfil) — الگوی `safety/redact.py` + یک `threat_patterns` مینیمال؛ مهارت پروژه‌ای (`.comodor/skills`) فقط بعد از trust صریح (الگوی `workspace.py`).

## نقشه‌ی پیاده‌سازی

1. `tools/skill_manage.py` — action ها با اعتبارسنجی مسیر (symlink و path-traversal رد — الگوی path_security ابزار مرجع).
2. `skills/linter.py` — شروع با ۶ قاعده؛ تست‌های واحد جدا.
3. `skills/usage.py` + `skills/ledger.py` — نوشتن اتمیک + قفل فایل.
4. اتصال matching نردبانی به پچ؛ preview در شکست.
5. `prompts.py`: یک بند در tool guidance («بعد از روال چند-گامی موفق، پیشنهاد مهارت بده») — در بخش ثابت تا cache نشکند.
6. `/skills` گسترش: tab usage + pending + diff.
7. تست: پچ مبهم = preview، rollback ledger، مهارت پروژه‌ای untrusted، injection در SKILL.md.

## پذیرش و تست

- بعد از یک workflow چند-گامی موفق، ایجنتی پیشنهاد مهارت بدهد؛ تأیید → فایل در ~/.comodor/skills + رکورد ledger.
- پچ نادرست (دو جا match) → خطا با preview، نه خرابی فایل.
- `comodor skills rollback --id` آخرین پچ را برگرداند (متن byte-به-byte).
- linter ارجاع `grep در bash` را به ابزار `grep`native اشاره کند.
