# Из терминала

Каждая команда и флаг, с тем, что можно вставить и запустить.

```bash
comodor help              # текстовая страница помощи
comodor help computer     # одна тема подробнее
```

---

## Установка и обновление

```bash
curl -fsSL get.comodor.ai | sh     # macOS, Linux, BSD
```

```powershell
irm get.comodor.ai | iex          # Windows
```

`get.comodor.ai` не содержит имени файла: он определяет, какой клиент спрашивает,
и отвечает установщиком, который этот клиент может выполнить. Та же одна строка
обновляет существующую установку. Или, когда Comodor уже на вашей машине:

```bash
comodor update --check    # что появилось
comodor update            # перейти на него
```

Остальное — в [Начале работы](getting-started.md#1-install): менеджеры пакетов
и что принимают установщики.

---

## Запуск

```bash
comodor                              # интерфейс
comodor --demo                       # интерфейс, офлайн, без ключа
comodor --resume                     # открыть последнюю сессию заново
comodor --resume 2026-08-22-a4f1     # открыть одну по id
comodor --cwd ~/projects/api         # работать где-то в другом месте
comodor --model claude-sonnet-5      # другая модель, только для этого запуска
comodor --mode plan                  # запустить в режиме только чтения
```

### Опции

| | |
|---|---|
| `--provider NAME` | `openrouter`, `anthropic`, `openai`, `ollama`, … |
| `--model ID` | переопределить модель для этого запуска |
| `--mode act\|plan\|chat` | plan — только чтение; у chat нет инструментов |
| `--no-loop` | ответить один раз вместо работы до завершения |
| `--cwd PATH` | папка, к которой он может прикасаться |
| `--theme NAME` | `ember`, `midnight`, `matrix`, `mono` |
| `--ascii` | ASCII-рамки |
| `--no-mouse` | оставить мышь терминалу |
| `--resume [ID]` | последняя сессия или одна по id |
| `--demo` | сценарный офлайн-провайдер |
| `--version` | какая это версия |
| `-h`, `--help` | текстовая страница помощи |

Ни одна из этих опций не записывается в вашу конфигурацию. Они действуют на один
запуск. Чтобы изменение закрепилось, используйте `/save` внутри интерфейса или
отредактируйте файл конфигурации — [Конфигурация](configuration.md).

---

## `comodor run` — одна задача, без интерфейса

```bash
comodor run "fix the failing test in tests/test_parser.py"
comodor run "add type hints to src/parser.py" --yes
comodor run "what does this project do?" --json
comodor run "refactor the parser" --max-steps 40
```

| | |
|---|---|
| `--yes` | автоматически подтверждать записи и команды |
| `--json` | машиночитаемый результат на stdout |
| `--max-steps N` | переопределить лимит шагов для этого запуска |

Без `--yes` он спросит — в stderr — и откажется, а не станет предполагать, если
ответить некому. Это намеренно: скрипт, который молча подтверждает сам себя, —
это скрипт, который делает нечто неожиданное в три часа ночи.

`--json` выдаёт:

```json
{
  "text": "Fixed. The parser raised on empty input rather than returning [\"\"] …",
  "ok": true,
  "stopped": "done",
  "steps": 6,
  "tool_calls": 11,
  "error": "",
  "usage": {
    "input_tokens": 18422,
    "output_tokens": 640,
    "cost_usd": 0.031
  },
  "elapsed": 24.71
}
```

`stopped` говорит, чем он закончил, — одно из:

| | |
|---|---|
| `done` | он сам решил, что закончил |
| `max_steps` | он упёрся в `agent.max_steps` |
| `budget` | он упёрся в `agent.max_cost_usd` или `agent.max_seconds` |
| `cancelled` | вы его прервали |
| `error` | что-то пошло не так; `error` говорит, что именно |

`ok` истинно для `done` и `max_steps` — нехватка шагов не провал, а потолок,
делающий своё дело, — так что если нужна разница, проверяйте и `stopped`:

```bash
comodor run "update the changelog for this release" --yes --json > result.json
jq -e '.stopped == "done"' result.json
```

Он учится и по headless-запуску. Исправление, внесённое вами потом, преподаёт
тот же урок, что и в интерактивной сессии.

---

## `comodor setup` — выбор провайдера и модели

```bash
comodor setup
```

Шесть вопросов, или семь, если установлен другой агент и он предлагает импорт.
Запускается автоматически при первом запуске; используйте это, чтобы передумать
позже.

Ответы попадают в `~/.comodor/config.json`.

---

## `comodor import` — из OpenClaw или Hermes

```bash
comodor import             # перенести ключи, модель и навыки
comodor import --dry-run   # сказать, что взял бы, ничего не меняя
comodor import --keys-only # оставить навыки и модель
```

Ничего не перемещается, и ничто уже настроенное здесь не заменяется. См.
[Переход от другого агента](migrating.md).

---

## `comodor doctor` — всё ли в порядке?

```bash
comodor doctor
comodor doctor --fix
```

```
  ok    config file         ~/.comodor/config.json
  ok    config permissions  0o600
  ok    provider            Anthropic · claude-sonnet-5
  ok    model               claude-sonnet-5
  ok    spend limit         $2.00 per task
  ok    brain               ~/.comodor/brain.db
  ok    skills              4 loaded
  warn  version             0.8.9 installed; 0.9.0 is out
```

`--fix` исправляет то, что исправимо, — устаревшее имя провайдера, отсутствующий
каталог, сломанный поисковый индекс. Он никогда не меняет то, о чём не сообщил
сначала.

Код выхода ненулевой, если что-то не прошло проверку, так что он годится для
health check.

---

## `comodor web` — из браузера

```bash
comodor web                       # здесь, на 127.0.0.1:8765
comodor web --port 9000
comodor web --host 0.0.0.0        # доступно извне — прочтите предупреждение
comodor web --no-browser          # не открывать браузер
comodor web --token mytoken       # фиксированный токен вместо нового
```

Полное руководство: [Из браузера](web.md).

---

## `comodor telegram` — с вашего телефона

```bash
comodor telegram connect <token>  # бот от @BotFather
comodor telegram pair             # одноразовый код, добавляющий ваш аккаунт
comodor telegram start            # здесь, занимая этот терминал
comodor telegram start -b         # отдельно; переживёт закрытие терминала
comodor telegram stop             # остановить фоновый
comodor telegram service install  # запускать при входе, чтобы ребут возвращал его
comodor telegram service show     # прочитать unit, прежде чем доверять
comodor telegram status           # что настроено, кому можно говорить, работает ли
comodor telegram writes on        # разрешить реплике с телефона править файлы
comodor telegram writes off
comodor telegram forget 12345     # отозвать один аккаунт
comodor telegram forget all
comodor telegram off              # остановить, ничего не забывая
```

Настройка первого запуска предлагает всё это последним вопросом; эти команды —
чтобы изменить потом или для уже настроенной машины.

Полное руководство: [С телефона](telegram.md).

---

## `comodor slack` — из рабочего пространства Slack

```bash
comodor slack manifest            # определение приложения для вставки в Slack
comodor slack connect             # два токена, проверяемые по мере вставки
comodor slack pair                # одноразовый код, добавляющий ваш аккаунт
comodor slack start               # здесь, занимая этот терминал
comodor slack start -b            # отдельно
comodor slack stop
comodor slack service install     # запускать при входе
comodor slack status              # что настроено, кому можно говорить, работает ли
comodor slack writes on           # разрешить реплике в Slack править файлы
comodor slack forget U01234567
comodor slack off
```

Около пяти минут, и без публичного адреса: Socket Mode заставляет приложение
открывать websocket наружу, а не принимать POST-запросы.

Полное руководство: [Из Slack](slack.md).

---

## `comodor whatsapp` — с номера WhatsApp

```bash
comodor whatsapp connect          # пошагово: линкует каждую страницу, проверяет каждое значение
comodor whatsapp connect --number-id … --token … --app-secret …
comodor whatsapp webhook          # что вставить в панель Meta
comodor whatsapp pair             # одноразовый код, добавляющий ваш номер
comodor whatsapp start            # здесь, занимая этот терминал
comodor whatsapp start --tunnel   # и поднять с ним туннель Cloudflare
comodor whatsapp start -b         # отдельно
comodor whatsapp stop
comodor whatsapp service install  # запускать при входе
comodor whatsapp status           # что настроено, кому можно говорить, работает ли
comodor whatsapp writes on        # разрешить реплике с телефона править файлы
comodor whatsapp forget 15551234567
comodor whatsapp off
```

Meta доставляет сообщения на URL, а не позволяет их опрашивать, поэтому этому
каналу нужен публичный HTTPS-адрес. `connect` без аргументов проводит всю
настройку и сам поднимает туннель; в первый раз — около двадцати минут, большей
частью в панели Meta. Ни настоящего номера, ни карты, ни бизнес-верификации.

Полное руководство: [Из WhatsApp](whatsapp.md).

---

## `comodor skills` — процедуры, которым он следует

```bash
comodor skills browse             # что доступно
comodor skills list               # что у вас есть
comodor skills add review taste   # установить несколько
comodor skills update             # обновить установленные
comodor skills remove review
```

Полное руководство: [Навыки](skills.md).

---

## `comodor mcp` — серверы Model Context Protocol

```bash
comodor mcp list                  # что у вас есть и что он предлагает
comodor mcp catalogue             # что доступно
comodor mcp add filesystem        # из каталога
comodor mcp custom NAME -- CMD    # своя собственная команда
comodor mcp remote NAME URL       # HTTP-сервер
comodor mcp enable NAME
comodor mcp disable NAME
comodor mcp remove NAME
comodor mcp test NAME             # подключиться и перечислить его инструменты
```

Полное руководство: [Серверы MCP](mcp.md).

---

## `comodor update` — переход к новейшему релизу

```bash
comodor update --check     # что появилось, ничего не меняя
comodor update             # сделать это
```

Он выясняет, как была установлена эта копия, — `uv`, `pipx`, `pip` или checkout
из исходников — и использует подходящее. Checkout из исходников оставляется
в покое: он ваш.

---

## `comodor uninstall` — удалить полностью

```bash
comodor uninstall --dry-run    # перечислить, что было бы удалено
comodor uninstall              # спросить, затем сделать
comodor uninstall --yes        # для скриптов
```

```
Your data
  everything it has learned and everything you told it     4.2 MB
    ~/.comodor
    settings and your API key · 812 lessons · 47 sessions · 4 skills

In your projects
  api-server                                               128 KB
    ~/projects/api-server/.comodor
    checkpoints, project settings, project skills

The program
  the uv installation
    ~/.local/share/uv/tools/comodor

4.3 MB across 3 places. None of it can be undone.
```

Он называет всё, прежде чем что-то удалять, и говорит, чего не смог найти, —
папку `.comodor` в проекте, которым вы пользовались, но чья история сессий
очищена, назвать нельзя, и он так и говорит, а не притворяется.

---

## `comodor preview` — интерфейс заданного размера

```bash
comodor preview 80x24
comodor preview 200x50 --svg wide.svg
```

Отрисовывает один кадр и завершается. Полезно для проверки узкого терминала
или для скриншота.

---

## Переменные окружения

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, … | ключ, по одному на провайдера |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | принудительно задать провайдера или модель |
| `COMODOR_HOME` | где живут конфигурация, brain и сессии |
| `COMODOR_BANNER=0` | без логотипа в этом запуске |
| `COMODOR_NO_IMPORT=1` | не предлагать импорт от другого агента |
| `COMODOR_WEB_TOKEN` | фиксированный токен для веб-интерфейса |
| `NO_COLOR` | без цвета, учитывается везде |

Ключ в окружении **никогда не записывается в ваш файл конфигурации**.
Экспортировать его, а не сохранять, — это решение, и `/save` его уважает. См.
[Конфигурация](configuration.md).

---

## Коды выхода

| | |
|---|---|
| `0` | сработало |
| `1` | не сработало |
| `130` | вы его прервали |

---

## См. также

- [Интерфейс](interface.md) — та же мощь, но интерактивно
- [Конфигурация](configuration.md) — сделать флаг постоянным
- [Устранение неполадок](troubleshooting.md) — когда команда не делает то, что обещает
