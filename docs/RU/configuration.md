# Конфигурация

Один JSON-файл, который никогда не нужно править руками, — но вот всё, что в нём
есть.

---

## Где что живёт

| | |
|---|---|
| `~/.comodor/config.json` | ваш. Его пишет мастер настройки; права только у владельца |
| `~/.comodor/brain.db` | чему он научился |
| `~/.comodor/sessions/` | каждый разговор |
| `~/.comodor/skills/` | навыки, которые вы установили или написали |
| `./.comodor/config.json` | проектный. Безопасно коммитить — см. [что он может задавать](safety.md#what-a-repository-may-set) |
| `./.comodor/checkpoints/` | прежнее содержимое каждого изменённого им файла |

На Windows `~/.comodor` — это `%APPDATA%\Comodor`. `COMODOR_HOME` переопределяет
это везде.

```bash
comodor doctor      # говорит точно, где находится всё перечисленное
```

---

## Что имеет приоритет

Четыре слоя. Поздний побеждает ранний.

```
1. built-in defaults
2. ~/.comodor/config.json         yours
3. ./.comodor/config.json         the project's — restricted
4. environment variables          ANTHROPIC_API_KEY, COMODOR_MODEL, …
5. the command line               --model, --mode, … for one run
```

### Что записывает `/save`

**Только то, что вы выбрали.** Это важнее, чем звучит.

Конфигурация, на которой работает агент, — это все четыре слоя, слитые вместе.
Записать её обратно в ваш файл — значило бы сделать потолок расходов клонированного
репозитория вашим постоянным глобальным дефолтом и скопировать на диск API-ключ,
который вы намеренно держали в окружении.

Поэтому `/save` помнит, откуда пришло каждое значение. Значение, которое всё ещё
держится на заимствованном слое, возвращается к тому, что говорил *ваш* файл;
значение, которое вы изменили за сессию, — ваше, и оно записывается.

- `/model x`, затем `/save` → сохраняет `x`
- `/save` в репозитории, закрепляющем `max_cost_usd: 500` → не сохраняет ничего
  подобного
- `/save` с экспортированным `ANTHROPIC_API_KEY` → ключ остаётся в вашем окружении

---

## Все настройки

### `provider` и `model`

```json
{ "provider": "anthropic", "model": "claude-sonnet-5" }
```

См. [Выбор модели](models.md).

### `agent` — как он работает

```json
{
  "agent": {
    "mode": "act",
    "loop": true,
    "max_steps": 0,
    "max_seconds": 3600.0,
    "max_cost_usd": 2.0,
    "context_limit": 1000000,
    "compact_at": 0.75,
    "temperature": 0.3,
    "max_output_tokens": 8192,
    "max_tool_chars": 12000,
    "keep_screenshots": 2,
    "system_prompt_extra": "",
    "prompt_cache": true,
    "prompt_cache_ttl": "5m"
  }
}
```

| | |
|---|---|
| `mode` | `act`, `plan` (только чтение), `chat` (без инструментов) |
| `loop` | работать до завершения или ответить один раз |
| `max_steps` | **`0` — без лимита, и это значение по умолчанию.** Рефакторинг на дюжине файлов упёрся в двадцать четыре шага на полуслове, а число шагов никак не связано с вредом. Задайте число, чтобы вернуть лимит |
| `max_seconds` | час. `0` — без лимита |
| `max_cost_usd` | потолок, отображающийся на цену того, что может пойти не так, — [если у модели есть опубликованный тариф](cost.md#when-the-limit-cannot-fire). `0` — без лимита |
| `context_limit` | индикатор. При смене модели следует за ней автоматически |
| `compact_at` | суммировать историю, когда она переходит эту долю лимита |
| `max_tool_chars` | сколько результата одного инструмента доходит до модели. Остальное записывается в файл, и ему говорят, как его прочитать, — а не обрезается |
| `keep_screenshots` | сколько скриншотов остаётся в разговоре. [Почему](computer.md#screenshots-and-what-they-cost) |
| `system_prompt_extra` | ваши собственные постоянные инструкции |
| `prompt_cache` | разрешить провайдеру повторно отдавать неизменный префикс. [Стоимость](cost.md) |
| `prompt_cache_ttl` | `5m` или `1h`. Час дороже при записи |

### `safety` — что он может делать

```json
{
  "safety": {
    "auto_approve_safe": true,
    "auto_approve_writes": false,
    "auto_approve_shell": false,
    "checkpoints": true,
    "workspace_only": true,
    "allow_commands": [],
    "deny_commands": ["rm -rf /", "..."],
    "max_file_read_bytes": 512000,
    "max_file_scan_bytes": 64000000,
    "trusted_folders": []
  }
}
```

Полное объяснение: [Безопасность и разрешения](safety.md).

### `learning` — что он помнит

```json
{
  "learning": {
    "enabled": true,
    "top_k": 6,
    "max_playbook_tokens": 800,
    "reflect": true,
    "reflect_model": "",
    "min_confidence": 0.15,
    "half_life_days": 45.0,
    "share_scope": "project",
    "associative": true,
    "corrections": true,
    "rules": true,
    "announce": true,
    "prefetch": true
  }
}
```

| | |
|---|---|
| `top_k` | уроков, вспоминаемых за ход |
| `max_playbook_tokens` | жёсткий потолок на то, что воспоминание может внедрить |
| `reflect` | дистиллировать уроки после задачи — эта опция стоит вызова модели |
| `reflect_model` | подешевле модель для этого, если хотите |
| `half_life_days` | как быстро угасает неиспользуемый урок |
| `share_scope` | `project` или `global` |
| `corrections`, `rules`, `announce`, `prefetch` | быстрая полоса — бесплатно, без вызова модели, работает даже при выключенном `reflect` |

Полное объяснение: [Как он учится](learning.md).

### `ui` — как он выглядит

```json
{
  "ui": {
    "theme": "ember",
    "ascii_borders": false,
    "mouse": true,
    "max_fps": 20,
    "show_timestamps": false,
    "sidebar": true,
    "banner": true,
    "syntax_theme": ""
  }
}
```

`banner: false` выключает логотип насовсем; `COMODOR_BANNER=0` — на один запуск.

### `skills` — процедуры

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000,
    "install_examples": true
  }
}
```

Полное объяснение: [Навыки](skills.md).

### `telegram` — с вашего телефона

```json
{
  "telegram": {
    "enabled": false,
    "token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300
  }
}
```

| | |
|---|---|
| `enabled` | запускает ли `comodor telegram start` бота |
| `token` | от [@BotFather](https://t.me/botfather). Настройка первого запуска его спрашивает, либо `comodor telegram connect` |
| `allowed` | числовые id пользователей Telegram, которым он отвечает, — и никому больше. Заполняется `comodor telegram pair`, никогда со стороны Telegram |
| `allow_writes` | может ли ход, начатый с телефона, править файлы и выполнять команды. В выключенном состоянии он удерживается в режиме plan, как бы ни был настроен терминал |
| `pair_window` | сколько секунд действует код сопряжения |

**Проектный `.comodor/config.json` не может задавать ничего из этого.** Репозиторий,
который мог бы добавить аккаунт в `allowed`, был бы бэкдором, и, в отличие от
браузера или экрана, при этом не было бы видно ничего происходящего.

Полное объяснение: [С телефона](telegram.md).

### `slack` — из рабочего пространства Slack

```json
{
  "slack": {
    "enabled": false,
    "bot_token": "",
    "app_token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300,
    "team": ""
  }
}
```

| | |
|---|---|
| `bot_token` | `xoxb-…` из OAuth & Permissions. Делает всё, что делает бот |
| `app_token` | `xapp-…` из Basic Information, scope `connections:write`. Открывает websocket Socket Mode — и больше ничего |
| `allowed` | id пользователей Slack, которым он отвечает. Не отображаемые имена: отображаемое имя может сменить его владелец |
| `allow_writes` | Может ли ход в Slack править файлы и выполнять команды |
| `pair_window` | Сколько секунд действует код сопряжения |
| `team` | Рабочее пространство, к которому он был подключён; запоминается, чтобы `status` мог назвать его без лишнего запроса |

**Проектный `.comodor/config.json` не может задавать ничего из этого** — по той же
причине, что и для остальных: репозиторий, который мог бы добавить аккаунт в
`allowed`, был бы бэкдором.

Полное объяснение: [Из Slack](slack.md).

### `whatsapp` — с номера WhatsApp

```json
{
  "whatsapp": {
    "enabled": false,
    "token": "",
    "phone_number_id": "",
    "app_secret": "",
    "verify_token": "",
    "allowed": [],
    "allow_writes": false,
    "host": "127.0.0.1",
    "port": 8770,
    "path": "/whatsapp",
    "public_url": "",
    "api_version": "v21.0"
  }
}
```

| | |
|---|---|
| `token` | Токен доступа Meta. Токен System User не истекает; собственный токен панели действует 24 часа |
| `phone_number_id` | Числовой id, который Meta показывает рядом с номером, а не сам номер |
| `app_secret` | Каждый webhook подписан им. Без него не проверяется ничто |
| `verify_token` | Возвращается эхом при одноразовом рукопожатии Meta. Генерируется, а не выбирается |
| `allowed` | Номера, которым он отвечает, сравниваются как цифры. Все остальные получают тишину |
| `allow_writes` | Может ли ход в WhatsApp править файлы и выполнять команды |
| `host`, `port`, `path` | Где слушает webhook. Localhost, позади чего-то, что терминирует TLS |
| `public_url` | Адрес, на который Meta доставляет сообщения; запоминается, чтобы `whatsapp webhook` мог его напечатать |
| `api_version` | Закреплена, потому что Meta выводит версии из эксплуатации по своему календарю, а не по вашему |

**Проектный `.comodor/config.json` не может задавать ничего из этого** — по той же
причине, что и `telegram`: репозиторий, который мог бы добавить номер в `allowed`,
был бы бэкдором, у которого не было бы на экране ничего, показывающего, что он
срабатывает.

Полное объяснение: [Из WhatsApp](whatsapp.md).

### `browser` — настоящий браузер

```json
{
  "browser": {
    "executable": "",
    "headless": true,
    "width": 1280,
    "height": 800,
    "port": 0
  }
}
```

`headless: false` — это способ смотреть, как он работает. `port` подключается
к браузеру, который вы запустили сами, так что он может использовать сессию,
в которую вы уже вошли, вместо того чтобы передавать ему ваш профиль.

Полное объяснение: [Настоящий браузер](browser.md).

### `computer` — ваш экран

```json
{
  "computer": {
    "enabled": false,
    "screenshot_tokens": 1600,
    "grant_seconds": 900,
    "travel_seconds": 0.32,
    "overlay": true,
    "never": []
  }
}
```

Полное объяснение: [Использование экрана](computer.md).

### `gateway` — маршрутизация между провайдерами

```json
{
  "gateway": {
    "enabled": false,
    "policy": "quality",
    "chain": [],
    "failure_threshold": 3,
    "cooldown_seconds": 60.0
  }
}
```

`policy` — это `cost`, `speed` или `quality`. С `enabled: true` он выбирает из
`chain` и обходит провайдера, который постоянно отказывает. `F5` или `/gw` в
интерфейсе.

### `mcp` — серверы Model Context Protocol

```json
{
  "mcp": {
    "enabled": true,
    "servers": { }
  }
}
```

Управляется через `comodor mcp`, а не вручную. [Серверы MCP](mcp.md).

---

## Переменные окружения

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, … | по одной на провайдера |
| `<PROVIDER>_BASE_URL`, `<PROVIDER>_MODEL` | переопределить эндпоинт или модель |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | принудительно задать и то и другое |
| `COMODOR_HOME` | где живёт всё |
| `COMODOR_BANNER=0` | без логотипа |
| `COMODOR_NO_IMPORT=1` | не предлагать импорт от другого агента |
| `COMODOR_WEB_TOKEN` | фиксированный токен для веб-интерфейса |
| `NO_COLOR` | без цвета |

---

## Когда настройка не вступает в силу

Comodor говорит об этом, а не игнорирует вас:

```
config: agent.max_steps must be a whole number; keeping 24
config: this project cannot set safety, computer — only your own can
```

Значение неверного типа приводится там, где это однозначно, и отвергается там,
где нет, а отказ называет ключ и то, что ожидалось. `null` не заменяет молча
строку на `None`.

Если настройка всё ещё будто ничего не делает:

```bash
comodor doctor          # что он на самом деле загрузил
```

```
/settings               # то же самое, в интерфейсе
```
