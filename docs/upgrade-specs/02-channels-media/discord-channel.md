# Spec: کانال Discord

> **EN summary:** Discord is the most-requested missing channel. ابزار مرجع ships a full Discord adapter (messages, threads, reactions, voice channels) plus Discord-specific tools. Comodor already has three hand-written channel bots (Telegram, Slack, WhatsApp) with a shared layer — this spec adds Discord as the fourth, following the exact same architecture: hand-written client over stdlib, allowlist of IDs, pairing code, writes-off-by-default. Uses the official REST API with a bot token (no gateway WebSocket in v1; polling via Slack-Socket-Mode-style is not available, so v1 uses webhooks or a single-shard gateway over the existing `net/ws.py`). Priority **P0** (largest user base gap), effort **L**.

## قابلیت در ابزار مرجع چطور است

مرجع: `gateway/` آداپتور discord، `tools/discord_tool.py`.

- پیام/thread/reaction/typing/streaming با message-edit؛ feature matrix هر پلتفرم مستند.
- ابزارهای `discord` و `discord_admin` در toolset جدا (فقط وقتی کانال فعال).
- مودهای busy-input، idle-reset per-platform (Discord ۶۰ دقیقه در ابزار مرجع).

## جای آن در Comodor

- الگوی کامل آماده است: `slack/bot.py` + `slack/socket.py` (WebSocket روی stdlib از `net/ws.py`) — Discord gateway هم WebSocket با heartbeat و IDENTIFY است؛ همان client قابل سازگارسازی است.
- `channels/daemon.py` (daemon + autostart)، `channels/unit.py`، `channels/markdown.py` (تبدیل Markdown به markup هدف — Discord از خود markdown پشتیبانی می‌کند؛ ساده‌ترین کانال)، `channels/settings.py` (بازخوانی کانفیگ زنده).
- اجزای جدید: `src/comodor/discord/` با `api.py` (REST: ارسال/ویرایش/واکنش با rate-limit handling از `net/http.py`)، `gateway.py` (WebSocket gateway: IDENTIFY، HEARTBEAT، resume)، `bot.py` (dispatch همان shape سه بات فعلی)، `commands.py` (دستورات `/model`، `/status` و… همان جدول `telegram/commands.py`).

## طراحی پیشنهادی

```
کانفیگ: discord.enabled=false, discord.token=null,
        discord.allowed_ids=[], discord.allow_writes=false,
        discord.idle_reset_minutes=60, discord.thread_replies=true
امنیت:  allowlist از snowflake ID (هرگز username)؛ pairing یک‌بارمصرف مثل سه کانال دیگر
        (کد در ترمینال تایپ می‌شود)؛ توکن هرگز در log/redact نشود
TUI:    comodor discord connect  → راهنمای ساخت اپ + توکن (الگوی whatsapp/guide.py)
        /discord در TUI؛ پنل در web UI
```

- v1 scope: پیام متنی DM + سرور، thread reply، streaming با ویرایش پیام (فاصله‌ی rate-limit)، attachment دانلود (ورودی فایل — پل به spec `inbound-media.md`)، typing indicator.
- v1 خارج از scope: voice channel (پل به spec `voice-tts-stt.md`)، slash commands رسمی Discord، reactions-to-agent.
- **Rate limit:** Discord سر-روت limit دارد؛ از connection pool موجود `net/http.py` با 429-retry و `X-RateLimit-Remaining` استفاده شود؛ الگوی backoff موجود `telegram/api.py`.
- **Idle reset:** همان مکانیزم `channels/settings.py` که Telegram دارد.

## نقشه‌ی پیاده‌سازی

1. `discord/api.py` — REST client: sendMessage/editMessage/addReaction با split همان ۲۰۰۰ کاراکتر + embedها.
2. `discord/gateway.py` — WS: HELLO/IDENTIFY/HEARTBEAT/RESUME روی `net/ws.py`؛ intent های MESSAGE_CREATE + TYPING.
3. `discord/bot.py` — همان قرارداد `telegram/bot.py`: auth → session key (DM جدا از guild+channel) → صف → agent → تحویل.
4. `channels/markdown.py`: مسیر discord (بزرگترین زیرمجموعه‌ی مشترک؛ کد-فنس و bold مستقیم، جدول‌ها → code block).
5. `channels/daemon.py` + `unit.py`: سرویس discord همانند بقیه.
6. `commands.py`: همان ۲۹ دستور slash که TUI دارد، به style Discord.
7. تست: با mock WS (الگوی `tests/support/fake_mcp_server.py`) — resume بعد از قطع، allowlist، pairing، writes-off.

## پذیرش و تست

- DM از کاربر غیر allowlist → بی‌پاسخ (نه حتی «شما مجاز نیستید»).
- پیام ۳۰۰۰ کاراکتری درست split و ارسال شود؛ ویرایش استریم کمتر از rate limit بماند.
- `allow_writes=false` → فرمان write در هر جا رد شود با پیام شفاف.
- قطع شبکه → resume بدون از دست دادن پیام‌ها (Discord gateway resume).
