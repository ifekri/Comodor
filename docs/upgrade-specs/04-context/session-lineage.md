# Spec: Lineage جلسه + کامپرشن چند-ترایگری

> **EN summary:** ابزار مرجع's session store tracks lineage (parent/child across compressions) and runs compression proactively from multiple triggers (preflight threshold, near-limit before an API call, idle-resume, retry templates), physically splitting the SQLite session and rotating the session id. Comodor compresses only reactively, keeps one JSONL per session, and loses the "this session was forked from that one" trail — which breaks `search_history` precision (an FTS hit can point into a compressed-away section) and long-lived channel sessions. This spec adds a lineage header to session JSONL, proactive trigger checks, and post-compression index rebuild pointers. Priority **P1**, effort **M**.

## قابلیت در ابزار مرجع چطور است

مرجع: state store ابزار مرجع، `agent/conversation_compression.py`، `agent/context_engine.py`.

- **ترایگرها:** preflight (≥ آستانه)، pre-API (نزدیک سقف context/output قبل از call)، idle compaction (رزومه بعد از بیکاری)، retry (قالب‌های خطای too-large/token/count).
- کامپرشن SQLite session را **فیزیکی می‌شکند** و session_id می‌چرخاند؛ lineage پدر/فرزند حفظ می‌شود؛ جدول‌ها و memory-provider ها اطلاع داده می‌شوند.
- `compress_context` با pool نخ daemon؛ snapshot عمیق ورودی‌ها؛ `CompressionCommitFence` (اجرا هم‌زمان دوباره ممنوع).
- probe شروع: اگر مدل aux کوچک‌تر از حد، آستانه پایین بیاید یا رد شود.
- re-encode عکس‌های base64 بزرگ تا سقف پرووایدر (مثل 5MB آنتروپیک).

## جای آن در Comodor

- موجود (و خوب): `agent/context.py` (کامپرشن سه‌مرحله‌ای در مرز امن — حفظ شود)، `agent/staleness.py`، `session/store.py` (JSONL append)، `session/search.py` (FTS index جدا و rebuildable)، `agent/tokens.py` (کالیبراسیون واقعی usage — مبنای بهتر از تخمین صرف برای pre-API check).
- جدید: lineage در هدر JSONL + فاز پیش‌ proactive + همگام‌سازی جستجو.

## طراحی پیشنهادی

```
lineage: هدر JSONL یک فیلد lineage می‌گیرد:
  {"parent_session": id|null, "compressed_at_turns": [n,...], "branch_reason": "compression"}
  کامپرشن فعلی درون-جلسه‌ای است؛ اگر v2 کامپرشن-با-شکافتن انجام شود، فایل جدید
  session با parent شروع شود و id جدید (JSONL append-only را نشکن)
ترایگرهای اضافه (روی موجودی فعلی):
  - pre-API: قبل از هر call، اگر تخمین+calibration > 92٪ پنجره → کامپرشن اجباری
    (فقط زمان‌سنج ارزان، بدون LLM)
  - idle: در resume بعد از بیکاری >24h، بررسی و در صورت نیاز کامپرشن قبل از
    اولین turn — کاربر پیام «زمینه فشرده شد» ببیند
  - کانال‌ها: چون جلسات کانال هفته‌ها زنده‌اند، idle-trigger مهم‌ترین است
همگام‌سازی search:
  بعد از هر کامپرشن، رکوردهای FTS آن جلسه با marker «فشرده‌شده؛ خلاصه در turn n»
  به‌روزرسانی شود تا search_history به بخش‌های حذف‌شده اشاره نکند
  (الگوی «کامپرشن فقط در مرز» حفظ — هیچ turn زنده‌ای متوقف نشود)
fence: کامپرشن هم‌زمان دوم = رد (قفل درون-فرایندی؛ معادل CompressionCommitFence)
```

- **عکس‌ها:** اگر مدل‌ها image بگیرند (spec inbound-media)، قبل از کامپرشن drop-as-superseded رفتار فعلی گسترش یابد؛ re-encode از `desktop/png.py` (بدون وابستگی).
- probe: مدل فعلی پنجره‌اش از `providers/profile.py` می‌آید — چک یک‌باره در شروع جلسه؛ پنجره‌ی نامعلوم → آستانه‌ی محافظه‌کار.

## نقشه‌ی پیاده‌سازی

1. `session/store.py`: فیلد lineage در metadata + خواندن پدر در `/resume`.
2. `agent/context.py`: دو تریگر pre-API و idle + fence.
3. `session/search.py`: marker پس از کامپرشن + تست «بعد از کامپرشن هیچ hit منقضی».
4. تست: جلسه‌ی ۳۰۰-turnی شبیه‌سازی‌شده، pre-API دقیقاً یک‌بار فایر شود، بعد از کامپرشن نتایج جستجو معتبر.

## پذیرش و تست

- جلسه‌ی کانال زنده‌ی ۲ هفته‌ای هرگز به سقف پرووایدر برسد (idle compression).
- `/search` هیچ‌وقت نتیجه‌ای نشان ندهد که ادامه‌اش حذف شده باشد.
- `search_history` + lineage: «این جلسه ادامه‌ی جلسه‌ی X بود» دیده شود.
- رفتار کامپرشن فعلی (مرز امن، حفظ درخواست اصلی) regression نکند — تست‌های موجود.
