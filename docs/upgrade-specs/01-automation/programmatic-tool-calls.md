# Spec: فراخوانی برنامه‌ای ابزارها (execute_code / RPC)

> **EN summary:** ابزار مرجع's `execute_code` lets the model write a Python script that calls the agent's own tools over an RPC bridge — collapsing "read 12 files, grep each, summarize" pipelines into one LLM turn with zero intermediate context cost. Comodor's `run_python` runs plain Python with no tool access. This spec adds a tool-RPC bridge inside the existing sandboxed Python tool: a `comodor` in-process module (read-only tools only) that routes through the normal permission gate and overflow handling. Priority **P1**, effort **M**.

## قابلیت در ابزار مرجع چطور است

مرجع: `tools/code_execution_tool.py`، `tools/code_kernel.py`، `tools/daemon_pool.py`.

- ابزار `execute_code` یک کرنل Python ماندگار راه می‌اندازد؛ اسکریپت می‌تواند `ref_tools.read_file(...)` صدا بزند و نتیجه را مستقیم در حافظه پردازش کند.
- ادعا: «multi-step pipelines را در turn های کم‌زمینه جمع می‌کند» — نتایج میانی هرگز به LLM نمی‌روند؛ فقط مقدار بازگشتی نهایی.
- محدودسازی: متغیرهای env با نام KEY/TOKEN/SECRET/… بلاک می‌شوند؛ خروجی ابزارها با سقف سایز؛ کرنل بعد از timeout خاموش می‌شود.

## جای آن در Comodor

- موجود: `tools/shell.py` (اجراهای run_python با مجوز DANGEROUS)، `agent/loop.py` (اجراکننده‌ی ابزار و شماره‌گذاری گام)، `tools/overflow.py`، `safety/permissions.py`، `agent/events.py`.
- **طراحی متمایز — صادقانه‌تر از ابزار مرجع:** به‌جای کرنل ماندگار رو-به-بیرون، یک **پل درون-فرایندی** با سطح API کوچک:
  - فقط ابزارهای رده SAFE (`read_file`, `list_dir`, `glob`, `grep`, `todo_write`, `search_history`) از `tools/registry.py` با همان `Request` گیت صدا زده می‌شوند.
  - ابزارهای WRITE/DANGEROUS صریحاً در دسترس نیستند و تلاش فراخوانی، خطای توضیحی برمی‌گرداند (نه سکوت) — همان الگوی شفافیت `registry.py` برای ابزار ناشناس.
  - هر فراخوانی از پل = یک گام شمرده‌شده در بودجه‌ی گام/هزینه‌ی `agent/loop.py` (داخل سقف `max_cost_usd`) — در گزارش گام‌ها هم دیده شود.
- نتیجه‌ی نهایی اسکریپت از همان مسیر overflow می‌گذرد (انتقال نه حذف).

## طراحی پیشنهادی

```
ابزار:  run_python (به‌روزرسانی: پارامتر tools=true)
API:    comodor.tools.<name>(**kwargs) → str/dict  # فقط SAFE
        comodor.tools.list_available() → نام‌ها + schema خلاصه
کانفیگ: python.tool_bridge=true, python.bridge_max_calls=200, python.bridge_timeout_s=120
```

- پیاده‌سازی: یک `Bridge` object در `agent/loop.py` ساخته و به محیط run_python تزریق شود (نه RPC شبکه — درون‌فرایندی ساده‌تر و بدون سطح حمله‌ی اضافه؛ تفاوت عمدی با ابزار مرجع و مزیت وابستگی‌صفر).
- اجرای اسکریپت همان مسیر موجود `tools/shell.py` (subprocess ایزوله از TUI، ضرب‌الاجل، مجوز DANGEROUS).
- ثبت حساب: هر فراخوانی پل یک ردیف در accounting گام؛ اگر بودجه تمام شود، پل یخ می‌زند با پیام روشن.

## نقشه‌ی پیاده‌سازی

1. `agent/tool_bridge.py` — wrapper با whitelist SAFE، شمارش فراخوانی، timeout مجموع، و بازگشت خطای توضیحی برای ابزار غیرمجاز.
2. اتصال در `tools/shell.py` هنگام `tools=true`؛ env همچنان تمیز (بدون کلید) — الگوی `redact.py`.
3. `prompts.py`: یک پاراگراف راهنما وقتی پل فعال است («برای پیمایش‌های سنگین از run_python(tools=true) استفاده کن») — در بخش tool guidance تا prefix ثابت بماند.
4. سقف خروجی: مقدار بازگشتی > بودجه → مسیر `tools/overflow.py`.
5. تست: فراخوانی ابزار DANGEROUS باید خطا بدهد؛ شمارش فراخوانی، بودجه‌ی هزینه، crash وسط پل.

## پذیرش و تست

- «توضیح بده کدام فایل‌ها بیشترین import تکراری دارند» در یک turn حل شود با پل — بدون گردش ۱۰ گامی read/grep.
- گزارش `/cost` فراخوانی‌های پل را شمرده نشان دهد.
- هیچ مسیری از پل به write/shell/شبکه وجود نداشته باشد (تست نفوذ: `comodor.tools.run_shell` باید AttributeError بدهد).
