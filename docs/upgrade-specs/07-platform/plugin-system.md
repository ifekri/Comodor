# Spec: Plugin System

> **EN summary:** Comodor's extension points today are MCP servers, skills, and custom OpenAI-compatible endpoints — but there is no way to add a *native tool*, a lifecycle hook, or a CLI command without forking. Hermes has a plugin manager: plugins discovered from user dir, project dir, and pip entry points, registering tools/hooks/CLI commands through a context API. This spec adds a deliberately small plugin system: Python modules in `~/.comodor/plugins/<name>/` (v1 skips pip entry points — Comodor is pip-installed itself and dogfooding plugin-as-dir is simpler and safer), a tiny context API, and hook events at the boundaries that already exist in `events.py`. Security is the headline: project plugins are untrusted by default, and every plugin tool passes the normal risk gate. Priority **P2**, effort **M–L**.

## قابلیت در hermes چطور است

مرجع: `hermes_cli/plugins.py` (PluginManager).

- کشف از سه منبع: `~/.hermes/plugins/`، `.hermes/plugins/` پروژه، pip entry points.
- Plugin context API: register tool / hook / CLI command؛ hook ها در نقاط lifecycle (interception، metrics، guardrails)؛ `hermes plugins` UI تعاملی.
- `plugin_guard.py` + scanning برای پلاگین‌های پروژه‌ای.

## جای آن در Comodor

- موجود: `events.py` (EventBus — نقاط hook طبیعی)، `tools/registry.py` (ثبت ابزار — import-time از قبل!)، `cli.py` (ساب‌کامندها)، `skills/loader.py` (الگوی مسیرهای user/project)، `workspace.py` (trust پروژه).
- جدید: `src/comodor/plugins/` با `manager.py`، `api.py`، `cli.py`.

## طراحی پیشنهادی

```
کشف (v1):
  ~/.comodor/plugins/<name>/plugin.py     # همیشه قابل‌اعتماد (مال خود کاربر)
  .comodor/plugins/<name>/plugin.py       # untrusted تا comodor plugins trust <name>
  (v2: entry points — وقتی جامعه پلاگین بسازد)
plugin.py:
  def register(ctx):
      ctx.tool(name, schema, handler, risk="SAFE")       # → registry موجود
      ctx.on("agent:turn_end", fn)                        # → EventBus
      ctx.command("mycmd", fn)                            # → cli.py
      ctx.config_schema({...})                            # → اعتبارسنجی config
API ctx صریحاً نمی‌دهد: دسترسی به مغز/سشن/کلیدها (فقط اگر tool خودش SAFE/WRITE/
  DANGEROUS از گیت بگذرد — پلاگین همیشه مهمان گیت مجوز است)
امنیت (سرخط):
  - پلاگین پروژه‌ای بدون trust → load نمی‌شود؛ پیام روشن + دستور trust (الگوی workspace.py)
  - اسکن سطحی plugin.py هنگام trust: imports مشکوک (socket برای exfil نه،
    exec/eval، نوشتن در ~/.comodor) → هشدار قبل از تأیید آدم
  - خطای load پلاگین هرگز Comodor را بالا نیاورد: هر پلاگین در try/except با
    گزارش در /plugins و doctor
CLI:   comodor plugins list|trust|untrust|doctor
TUI:   /plugins — وضعیت، ابزارهای ثبت‌شده، رویدادهای hook
hook points (v1): agent:turn_start, agent:turn_end, tool:before (مجوزخواه از
  EventBus موجود قابل لغو — guardrail پلاگینی ممکن)، tool:after, session:start|end
```

- **چرا کوچک:** plugin system های بزرگ به بدهی تبدیل می‌شوند؛ v1 فقط سه capability (tool/hook/command) — همان چیزی که جامعه واقعاً می‌خواهد. MCP برای چیزهای سنگین هست.
- سازگاری: پلاگین tools در sidebar، در `run --json`، و در کانال‌ها همانند ابزارهای core ظاهر شوند (چون واقعاً در registry می‌نشینند).

## نقشه‌ی پیاده‌سازی

1. `plugins/api.py` — ctx با ۴ متد؛ اعتبارسنجی schema.
2. `plugins/manager.py` — کشف، trust، load ایزوله (import در فضای نام ماژول)، خطاهای جذب‌شده.
3. اتصال: `tools/registry.py` (متد add-runtime)، `events.py` (بدون تغییر — پلاگین مشترک می‌شود)، `cli.py` (ثبت ساب‌کامند).
4. اسکن trust + `/plugins` + doctor.
5. تست: پلاگین فیک (tool SAFE ثبت کند)، untrusted رد، خطای پلاگین → بقیه زنده، hook tool:before که یک دستور را بلاک کند.

## پذیرش و تست

- یک پلاگین نمونه در docs: «register a /deploy command» — کاربر در ۱۰ خط بتواند.
- پلاگین خراب → Comodor بالا بیاید و فقط در doctor شکایت کند.
- ابزار پلاگین از کانال تلگرام هم همان گیت مجوز را بگیرد.
