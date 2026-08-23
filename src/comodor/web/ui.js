/* Comodor in a browser.
 *
 * No framework, for the same reason the HTTP client is hand-rolled: this ships
 * inside a Python package with one dependency and has to work on a machine
 * that cannot reach a CDN. What replaces a framework is a small number of
 * rules, kept to strictly:
 *
 *   1. Model output is never handed to `innerHTML`. Every message is built out
 *      of text nodes. The agent reads files, and a file can contain a script
 *      tag; a transcript that renders one is a transcript that runs it.
 *   2. State lives in one object and the renderers read it. Nothing reads the
 *      DOM to find out what is true.
 *   3. Anything reporting a *setting* replaces the last thing that reported
 *      it. Anything reporting an *event* queues. Confusing the two is how a
 *      status line ends up showing three modes at once.
 */
'use strict';

/* ------------------------------------------------------------------ state */

const state = {
  cursor: 0,
  busy: false,
  live: true,
  mode: 'act',
  model: '',
  provider: '',
  project: '',
  chatId: '',
  usage: { prompt: 0, output: 0, cost: 0 },
  contextLimit: 0,
  admin: null,
};

const $ = (id) => document.getElementById(id);

const els = {
  shell: $('shell'), stream: $('stream'), log: $('log'), prompt: $('prompt'),
  send: $('send'), stop: $('stop'), mode: $('mode'), modeNote: $('mode-note'),
  ask: $('ask'), chats: $('chats'), find: $('find'), adminBody: $('admin-body'),
  status: $('status'), where: $('where'), gauge: $('gauge'), ctx: $('ctx'),
  spend: $('spend'), spendBit: $('spend-bit'), reflex: $('reflex'),
  reflexBit: $('reflex-bit'), tokens: $('tokens'), link: $('link'),
  whoProvider: $('who-provider'), whoModel: $('who-model'),
  screen: $('screen'), frame: $('frame'), caption: $('caption'),
  toasts: $('toasts'), scrim: $('scrim'),
};

const MODE_NOTE = {
  act: 'edits files and runs commands',
  plan: 'reads only — nothing is changed',
  chat: 'no tools at all',
};

/* -------------------------------------------------------------- direction
 *
 * Which way a piece of text runs, decided by counting rather than by the
 * first letter.
 *
 * `dir="auto"` uses the first strong character, so a Persian sentence opening
 * with a package name is set left-to-right and reads inside out. Testing for
 * *any* right-to-left character has the opposite fault: one Persian word in an
 * English paragraph flips the whole thing. Counting is right in both cases.
 *
 * Code, paths and URLs are removed before counting. They are always Latin and
 * always incidental, and a Persian answer quoting three file paths would
 * otherwise be judged an English one.
 */
const RTL_RE = /[֐-׿؀-ۿ܀-ݏݐ-ݿހ-޿ࢠ-ࣿיִ-﷿ﹰ-﻿]/g;
const LTR_RE = /[A-Za-zÀ-ɏΆ-ϿЀ-ӿ]/g;

function directionOf(text) {
  if (!text) return 'ltr';
  const prose = text
    .replace(/```[\s\S]*?(```|$)/g, ' ')
    .replace(/`[^`]*`/g, ' ')
    .replace(/\b[a-z][a-z0-9+.-]*:\/\/\S+/gi, ' ')
    .replace(/[~./\\][\w.\-/\\]{2,}/g, ' ');
  const rtl = (prose.match(RTL_RE) || []).length;
  if (!rtl) return 'ltr';
  const ltr = (prose.match(LTR_RE) || []).length;
  return rtl >= ltr ? 'rtl' : 'ltr';
}

/** Set direction on a node, and keep the class in step with it. */
function orient(node, text) {
  const dir = directionOf(text);
  if (node.getAttribute('dir') !== dir) node.setAttribute('dir', dir);
  return dir;
}

/* ----------------------------------------------------------------- talking */

function post(path, body) {
  return fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Comodor': '1' },
    body: JSON.stringify(body || {}),
  }).then((r) => r.json().catch(() => ({}))).catch(() => ({}));
}

function get(path) {
  return fetch(path).then((r) => (r.ok ? r.json() : null)).catch(() => null);
}

/* ------------------------------------------------------------------ toasts
 *
 * Keyed, so a second notice about the same setting replaces the first. There
 * is one current mode; showing three is showing two that are no longer true.
 */
const toastTimers = new Map();

function toast(text, tone, key) {
  if (key && toastTimers.has(key)) {
    clearTimeout(toastTimers.get(key).timer);
    toastTimers.get(key).node.remove();
    toastTimers.delete(key);
  }
  const node = document.createElement('div');
  node.className = 'toast' + (tone ? ' ' + tone : '');
  node.textContent = text;
  orient(node, text);
  els.toasts.appendChild(node);
  const timer = setTimeout(() => {
    node.remove();
    if (key) toastTimers.delete(key);
  }, 3600);
  if (key) toastTimers.set(key, { node, timer });
}

/* ------------------------------------------------------------- the stream */

let atBottom = true;
els.log.addEventListener('scroll', () => {
  atBottom = els.log.scrollHeight - els.log.scrollTop - els.log.clientHeight < 90;
});

function stick() {
  // The dots go last, always. They are appended the moment a turn starts,
  // which is before the user's own message has come back off the bus, so
  // being added last is not the same as being at the end.
  const dots = els.stream.querySelector('.thinking');
  if (dots && dots !== els.stream.lastElementChild) els.stream.appendChild(dots);
  if (atBottom) els.log.scrollTop = els.log.scrollHeight;
}

/**
 * Render text into a node: fenced code as code, everything else as text.
 *
 * Deliberately not a markdown parser. Fences and inline code are the two
 * things that are *wrong* as running prose - a diff rendered with its
 * whitespace collapsed is unreadable - and everything else survives being
 * left alone. Nothing here builds HTML from a string, so nothing the model
 * writes can become markup.
 */
function paint(node, text) {
  node.textContent = '';
  const parts = text.split(/```/);
  parts.forEach((part, index) => {
    if (index % 2 === 1) {
      const pre = document.createElement('pre');
      const code = document.createElement('code');
      const newline = part.indexOf('\n');
      // A fence may name its language on the opening line; that is a label,
      // not the first line of the snippet.
      code.textContent = newline >= 0 && !part.slice(0, newline).includes(' ')
        ? part.slice(newline + 1) : part;
      pre.appendChild(code);
      node.appendChild(pre);
      return;
    }
    part.split(/(`[^`\n]+`)/).forEach((piece) => {
      if (!piece) return;
      if (piece.length > 2 && piece.startsWith('`') && piece.endsWith('`')) {
        const code = document.createElement('code');
        code.textContent = piece.slice(1, -1);
        node.appendChild(code);
      } else {
        node.appendChild(document.createTextNode(piece));
      }
    });
  });
}

function turnNode(role, text) {
  const turn = document.createElement('div');
  turn.className = 'turn ' + role;

  const who = document.createElement('div');
  who.className = 'who';
  if (role === 'agent') {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 512 512');
    svg.setAttribute('fill', 'currentColor');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#i-mark');
    svg.appendChild(use);
    who.appendChild(svg);
    who.setAttribute('aria-label', 'Comodor');
  } else {
    who.textContent = 'You';
    who.style.fontSize = '10px';
  }

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  const body = document.createElement('div');
  body.className = 'text bidi';
  paint(body, text || '');
  orient(body, text || '');
  bubble.appendChild(body);

  turn.append(who, bubble);
  turn.body = body;
  return turn;
}

function say(role, text) {
  hideBlank();
  const node = turnNode(role, text);
  els.stream.appendChild(node);
  stick();
  return node;
}

function notice(text, bad) {
  hideBlank();
  const node = document.createElement('p');
  node.className = 'notice bidi' + (bad ? ' error' : '');
  node.textContent = text || '';
  orient(node, text || '');
  els.stream.appendChild(node);
  stick();
}

/* -- the message being streamed ------------------------------------------- */

let live = null;             // { node, text, dirty }
let repaint = 0;

function flushLive() {
  repaint = 0;
  if (!live) return;
  paint(live.node.body, live.text);
  orient(live.node.body, live.text);
  stick();
}

function stream(chunk) {
  if (!live) live = { node: say('agent', ''), text: '' };
  live.text += chunk;
  // Repainting on every token is quadratic on a long answer. One frame's
  // delay is imperceptible and turns it back into something linear.
  if (!repaint) repaint = requestAnimationFrame(flushLive);
}

function endStream(final) {
  if (live) {
    if (!live.text && final) live.text = final;
    flushLive();
    if (!live.text.trim()) live.node.remove();
  }
  live = null;
}

/* -- tool calls ------------------------------------------------------------ */

const running = new Map();

function toolRow(id, verb, target) {
  hideBlank();
  const box = document.createElement('details');
  box.className = 'tool';
  box.dataset.ok = 'true';

  const head = document.createElement('summary');
  const spinner = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  spinner.setAttribute('class', 'spin');
  spinner.setAttribute('viewBox', '0 0 20 20');
  spinner.setAttribute('fill', 'none');
  spinner.setAttribute('stroke', 'currentColor');
  spinner.setAttribute('stroke-width', '2.4');
  spinner.setAttribute('stroke-linecap', 'round');
  const arc = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  arc.setAttribute('d', 'M10 2.4a7.6 7.6 0 1 1-7.6 7.6');
  spinner.appendChild(arc);

  const name = document.createElement('span');
  name.className = 'verb';
  name.textContent = verb;

  const what = document.createElement('span');
  what.className = 'target';
  what.textContent = target || '';

  const took = document.createElement('span');
  took.className = 'took';
  took.textContent = '';

  head.append(spinner, name, what, took);
  box.appendChild(head);
  els.stream.appendChild(box);
  running.set(id, { box, head, spinner, took });
  stick();
  return box;
}

function toolDone(id, ok, elapsed, preview) {
  const row = running.get(id);
  if (!row) return;
  row.spinner.remove();
  row.box.dataset.ok = ok === false ? 'false' : 'true';
  row.took.textContent = (elapsed || 0).toFixed(1) + 's';
  const body = (preview || '').trim();
  if (body) {
    const pre = document.createElement('pre');
    pre.textContent = body.length > 6000 ? body.slice(0, 6000) + '\n…' : body;
    row.box.appendChild(pre);
    if (ok === false) row.box.open = true;
  }
  running.delete(id);
  stick();
}

/* ------------------------------------------------------------ empty state */

const STARTERS = [
  'Explain what this project does and how it is laid out.',
  'Find the slowest thing here and show me why.',
  'Write tests for the part with the least coverage.',
  'Review my last commit for anything that will bite later.',
];

function showBlank() {
  els.stream.textContent = '';
  const box = document.createElement('div');
  box.id = 'blank';

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'mark');
  svg.setAttribute('viewBox', '0 0 512 512');
  svg.setAttribute('fill', 'var(--accent)');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#i-mark');
  svg.appendChild(use);

  const head = document.createElement('h1');
  head.textContent = 'What would you like done?';
  const sub = document.createElement('p');
  sub.textContent = state.project
    ? 'Working in ' + state.project + '. It reads the code before it changes anything, '
      + 'and asks before anything it cannot undo.'
    : 'It reads the code before it changes anything, and asks before anything '
      + 'it cannot undo.';

  const grid = document.createElement('div');
  grid.className = 'starters';
  STARTERS.forEach((line) => {
    const button = document.createElement('button');
    button.className = 'starter';
    button.type = 'button';
    button.textContent = line;
    button.onclick = () => {
      els.prompt.value = line;
      grow();
      els.prompt.focus();
    };
    grid.appendChild(button);
  });

  box.append(svg, head, sub, grid);
  els.stream.appendChild(box);
}

function hideBlank() {
  const blank = $('blank');
  if (blank) blank.remove();
}

/* ------------------------------------------------------------- permission */

function askFor(event) {
  els.ask.hidden = false;
  els.ask.textContent = '';

  const question = document.createElement('p');
  question.className = 'q bidi';
  question.id = 'ask-q';
  question.textContent = event.prompt || 'Allow this?';
  orient(question, question.textContent);
  els.ask.appendChild(question);

  if (event.detail) {
    const detail = document.createElement('pre');
    detail.textContent = event.detail;
    els.ask.appendChild(detail);
  }

  const choices = document.createElement('div');
  choices.className = 'choices';
  const options = event.options && event.options.length ? event.options : ['yes', 'no'];
  options.forEach((option, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = option;
    if (index === 0) button.className = 'primary';
    button.onclick = () => {
      els.ask.hidden = true;
      post('/api/answer', { id: event.id, choice: option });
    };
    choices.appendChild(button);
  });
  els.ask.appendChild(choices);
  const first = els.ask.querySelector('button');
  if (first) first.focus();
}

/* ------------------------------------------------------------------ events */

function apply(event) {
  switch (event.kind) {
    case 'user_message': say('user', event.text); break;
    case 'assistant_start': live = null; break;
    case 'assistant_delta': stream(event.text || ''); break;
    case 'assistant_end': endStream(event.text); break;
    case 'tool_start': toolRow(event.id, event.name || 'tool', event.summary || ''); break;
    case 'tool_end': toolDone(event.id, event.ok, event.elapsed, event.display); break;
    case 'notice': notice(event.text); break;
    case 'error': endStream(); notice(event.text, true); break;
    case 'cancelled': endStream(); notice('Stopped.'); break;
    case 'request': askFor(event); break;
    case 'screen': showScreen(event); break;
    case 'turn_end': setBusy(false); break;
    case 'usage':
      state.usage.prompt = event.input_tokens || state.usage.prompt;
      state.usage.output = event.output_tokens || state.usage.output;
      state.usage.cost = event.cost_usd != null ? event.cost_usd : state.usage.cost;
      drawStatus();
      break;
    case 'status':
      if (typeof event.busy === 'boolean') setBusy(event.busy);
      if (event.mode) { state.mode = event.mode; drawMode(); }
      if (event.model) { state.model = event.model; drawWho(); }
      if (event.provider) { state.provider = event.provider; drawWho(); }
      break;
    default: break;
  }
}

/* -- the screen the agent is driving --------------------------------------- */

let markTimer = 0;

function showScreen(event) {
  els.screen.dataset.on = 'true';
  if (event.frame) els.frame.src = '/api/screen?n=' + event.frame;
  if (event.caption) els.caption.textContent = event.caption;

  const old = els.screen.querySelector('.mark');
  if (old) old.remove();
  if (typeof event.x !== 'number' || typeof event.y !== 'number') return;

  // Percentages, so the marker holds its place when the panel is resized. The
  // coordinates arrive in the frame's own pixels, which is the one measurement
  // both ends agree about.
  const width = event.width || els.frame.naturalWidth || 1;
  const height = event.height || els.frame.naturalHeight || 1;
  const mark = document.createElement('div');
  mark.className = 'mark';
  mark.style.insetInlineStart = (100 * event.x / width) + '%';
  mark.style.top = (100 * event.y / height) + '%';
  els.screen.appendChild(mark);

  clearTimeout(markTimer);
  markTimer = setTimeout(() => mark.remove(), 4200);
}

/* ------------------------------------------------------------------ chrome */

function setBusy(value) {
  state.busy = value;
  els.send.hidden = value;
  els.stop.hidden = !value;
  els.prompt.setAttribute('aria-busy', String(value));
  const already = els.stream.querySelector('.thinking');
  if (value && !already) {
    const dots = document.createElement('div');
    dots.className = 'thinking';
    dots.innerHTML = '<i></i><i></i><i></i>';
    els.stream.appendChild(dots);
    stick();
  } else if (!value && already) {
    already.remove();
  }
}

function drawWho() {
  els.whoProvider.textContent = state.provider || '—';
  els.whoModel.textContent = state.model || '—';
  document.title = state.model ? 'Comodor · ' + state.model : 'Comodor';
}

function drawMode() {
  els.mode.value = state.mode;
  els.modeNote.textContent = MODE_NOTE[state.mode] || '';
}

function drawStatus() {
  els.where.textContent = state.project || '—';
  els.where.title = state.project || '';

  const used = state.usage.prompt || 0;
  const limit = state.contextLimit || 0;
  const share = limit ? Math.min(1, used / limit) : 0;
  els.gauge.firstElementChild.style.width = (share * 100).toFixed(1) + '%';
  els.gauge.dataset.full = String(share > 0.85);
  els.ctx.textContent = Math.round(share * 100) + '%';

  if (state.usage.cost > 0) {
    els.spendBit.hidden = false;
    els.spend.textContent = '$' + state.usage.cost.toFixed(state.usage.cost < 1 ? 4 : 2);
  }

  const bits = [];
  if (state.usage.prompt) bits.push(state.usage.prompt.toLocaleString() + ' in');
  if (state.usage.output) bits.push(state.usage.output.toLocaleString() + ' out');
  els.tokens.textContent = bits.join(' · ');

  els.status.dataset.live = String(state.live);
  els.link.textContent = state.live ? 'connected' : 'reconnecting…';
}

/* -------------------------------------------------------------- chat list */

function whenGroup(updatedAt) {
  if (!updatedAt) return 'Earlier';
  const then = new Date(updatedAt * 1000);
  const now = new Date();
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (then >= midnight) return 'Today';
  if (then >= new Date(midnight.getTime() - 86400000)) return 'Yesterday';
  if (then >= new Date(midnight.getTime() - 6 * 86400000)) return 'This week';
  return 'Earlier';
}

function drawChats(chats) {
  els.chats.textContent = '';
  if (!chats.length) {
    const note = document.createElement('p');
    note.className = 'empty-note';
    note.textContent = els.find.value.trim()
      ? 'Nothing matches that.' : 'No chats yet. This one is the first.';
    els.chats.appendChild(note);
    return;
  }

  let group = '';
  chats.forEach((chat) => {
    const label = els.find.value.trim() ? '' : whenGroup(chat.updated_at);
    if (label && label !== group) {
      group = label;
      const heading = document.createElement('p');
      heading.className = 'group-label';
      heading.textContent = label;
      els.chats.appendChild(heading);
    }

    const row = document.createElement('button');
    row.className = 'chat-row';
    row.type = 'button';
    row.setAttribute('role', 'listitem');
    if (chat.id === state.chatId) row.setAttribute('aria-current', 'true');

    const title = document.createElement('span');
    title.className = 'title';
    title.textContent = chat.title;
    orient(title, chat.title);

    const meta = document.createElement('span');
    meta.className = 'meta';
    const facts = [chat.when];
    if (chat.messages) facts.push(chat.messages + ' messages');
    if (chat.cost) facts.push('$' + chat.cost.toFixed(4));
    meta.textContent = facts.join(' · ');

    row.append(title, meta);

    if (chat.snippet) {
      const snippet = document.createElement('span');
      snippet.className = 'snippet';
      snippet.textContent = chat.snippet;
      orient(snippet, chat.snippet);
      row.appendChild(snippet);
    }

    row.onclick = () => openChat(chat.id);

    if (chat.id !== state.chatId) {
      const drop = document.createElement('span');
      drop.className = 'drop';
      drop.setAttribute('role', 'button');
      drop.setAttribute('tabindex', '0');
      drop.setAttribute('aria-label', 'Delete ' + chat.title);
      drop.title = 'Delete';
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
      use.setAttribute('href', '#i-trash');
      svg.appendChild(use);
      drop.appendChild(svg);
      const remove = (ev) => {
        ev.stopPropagation();
        ev.preventDefault();
        if (!confirm('Delete “' + chat.title + '”? This cannot be undone.')) return;
        post('/api/chat', { action: 'delete', id: chat.id }).then((reply) => {
          if (reply.ok) { toast('Chat deleted', '', 'chat'); refreshChats(); }
          else toast(reply.error || 'Could not delete that', 'bad', 'chat');
        });
      };
      drop.onclick = remove;
      drop.onkeydown = (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') remove(ev);
      };
      row.appendChild(drop);
    }

    els.chats.appendChild(row);
  });
}

function refreshChats() {
  const query = els.find.value.trim();
  get('/api/chats' + (query ? '?q=' + encodeURIComponent(query) : ''))
    .then((data) => { if (data) drawChats(data.chats || []); });
}

function drawTurns(turns) {
  els.stream.textContent = '';
  live = null;
  running.clear();
  if (!turns.length) { showBlank(); return; }
  turns.forEach((turn) => {
    if (turn.kind === 'user') say('user', turn.text);
    else if (turn.kind === 'assistant') say('agent', turn.text);
    else if (turn.kind === 'tool') {
      const id = 'past-' + Math.random().toString(36).slice(2);
      toolRow(id, turn.name, '');
      toolDone(id, turn.ok, 0, turn.text);
      const row = els.stream.lastElementChild;
      if (row && row.classList.contains('tool')) {
        const took = row.querySelector('.took');
        if (took) took.textContent = '';
      }
    }
  });
  els.log.scrollTop = els.log.scrollHeight;
}

function openChat(id) {
  if (id === state.chatId) { closeRailIfNarrow(); return; }
  post('/api/chat', { action: 'open', id }).then((reply) => {
    if (!reply.opened) { toast(reply.error || 'Could not open that', 'bad', 'chat'); return; }
    state.cursor = reply.cursor || state.cursor;
    state.chatId = (reply.chat && reply.chat.id) || id;
    drawTurns(reply.turns || []);
    refreshChats();
    closeRailIfNarrow();
  });
}

function newChat() {
  post('/api/chat', { action: 'new' }).then((reply) => {
    if (!reply.ok) { toast(reply.error || 'Could not start one', 'bad', 'chat'); return; }
    state.cursor = reply.cursor || state.cursor;
    state.chatId = (reply.chat && reply.chat.id) || '';
    els.stream.textContent = '';
    live = null;
    running.clear();
    els.ask.hidden = true;
    els.screen.dataset.on = 'false';
    showBlank();
    refreshChats();
    els.prompt.focus();
    closeRailIfNarrow();
  });
}

/* ------------------------------------------------------------------ admin */

function row(parent, key, value) {
  const dt = document.createElement('dt');
  dt.textContent = key;
  const dd = document.createElement('dd');
  dd.textContent = value;
  parent.append(dt, dd);
}

function card(title) {
  const box = document.createElement('section');
  box.className = 'card';
  const head = document.createElement('h3');
  head.textContent = title;
  const body = document.createElement('div');
  body.className = 'body';
  box.append(head, body);
  els.adminBody.appendChild(box);
  return body;
}

function drawAdmin(data) {
  state.admin = data;
  els.adminBody.textContent = '';

  /* -- what answers ------------------------------------------------------ */
  {
    const body = card('Model');

    const providers = document.createElement('div');
    providers.className = 'control';
    const providerLabel = document.createElement('label');
    providerLabel.textContent = 'Provider';
    providerLabel.htmlFor = 'pick-provider';
    const providerPick = document.createElement('select');
    providerPick.id = 'pick-provider';
    data.model.providers.forEach((entry) => {
      const option = document.createElement('option');
      option.value = entry.id;
      option.textContent = entry.label + (entry.ready ? '' : ' — no key');
      option.disabled = !entry.ready;
      if (entry.id === data.model.provider) option.selected = true;
      providerPick.appendChild(option);
    });
    providerPick.onchange = () => change('provider', providerPick.value);
    providers.append(providerLabel, providerPick);

    const models = document.createElement('div');
    models.className = 'control';
    const modelLabel = document.createElement('label');
    modelLabel.textContent = 'Model';
    modelLabel.htmlFor = 'pick-model';
    const modelPick = document.createElement('select');
    modelPick.id = 'pick-model';
    data.model.models.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      if (name === data.model.model) option.selected = true;
      modelPick.appendChild(option);
    });
    modelPick.onchange = () => change('model', modelPick.value);
    models.append(modelLabel, modelPick);

    body.append(providers, models);
  }

  /* -- how far it goes on its own --------------------------------------- */
  {
    const body = card('How it runs');

    const modes = document.createElement('div');
    modes.className = 'control';
    const modeLabel = document.createElement('label');
    modeLabel.textContent = 'Mode';
    modeLabel.htmlFor = 'pick-mode';
    const modePick = document.createElement('select');
    modePick.id = 'pick-mode';
    ['act', 'plan', 'chat'].forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      // Just the name. The sentence explaining it went in the option text
      // first and was cut off by the width of the control it was in.
      option.textContent = name[0].toUpperCase() + name.slice(1);
      if (name === data.agent.mode) option.selected = true;
      modePick.appendChild(option);
    });
    const modeNote = document.createElement('p');
    modeNote.style.cssText = 'margin:2px 0 0;font-size:12px;color:var(--ink-faint)';
    modeNote.textContent = MODE_NOTE[data.agent.mode] || '';
    modePick.onchange = () => {
      modeNote.textContent = MODE_NOTE[modePick.value] || '';
      change('mode', modePick.value);
    };
    modes.append(modeLabel, modePick, modeNote);

    const loop = document.createElement('label');
    loop.className = 'switch';
    const loopText = document.createElement('span');
    loopText.textContent = 'Keep going without asking';
    const loopBox = document.createElement('input');
    loopBox.type = 'checkbox';
    loopBox.checked = !!data.agent.loop;
    loopBox.onchange = () => change('loop', loopBox.checked);
    const track = document.createElement('span');
    track.className = 'track';
    loop.append(loopText, loopBox, track);

    const facts = document.createElement('dl');
    facts.className = 'kv';
    facts.style.marginTop = '12px';
    row(facts, 'Context', data.agent.context_limit.toLocaleString() + ' tokens');
    row(facts, 'Compacts at', Math.round(data.agent.compact_at * 100) + '%');
    row(facts, 'Step limit', data.agent.max_steps || 'none');
    row(facts, 'Time limit', data.agent.max_seconds
      ? Math.round(data.agent.max_seconds / 60) + ' min' : 'none');
    row(facts, 'Spend limit', data.agent.max_cost_usd
      ? '$' + data.agent.max_cost_usd : 'none');

    body.append(modes, loop, facts);
  }

  /* -- what it may touch ------------------------------------------------- */
  {
    const body = card('Permissions');
    const pills = document.createElement('div');
    pills.className = 'pills';
    const flag = (label, on) => {
      const pill = document.createElement('span');
      pill.className = 'pill ' + (on ? 'on' : 'off');
      pill.textContent = label + (on ? ' · on' : ' · asks');
      pills.appendChild(pill);
    };
    flag('Reading', data.safety.auto_approve_safe);
    flag('Writing', data.safety.auto_approve_writes);
    flag('Commands', data.safety.auto_approve_shell);

    const facts = document.createElement('dl');
    facts.className = 'kv';
    facts.style.marginTop = '10px';
    row(facts, 'Undo copies', data.safety.checkpoints ? 'kept' : 'off');
    row(facts, 'Confined to', data.safety.workspace_only
      ? 'this folder' : 'anywhere');
    if (data.safety.grants.length) {
      row(facts, 'Granted', data.safety.grants.join(', '));
    }

    const note = document.createElement('p');
    note.style.cssText = 'margin:10px 0 0;font-size:12px;color:var(--ink-faint)';
    note.textContent = 'Changed where Comodor was started, not here — a page '
      + 'anyone with the link can open is the wrong place to widen what the '
      + 'agent may do.';

    body.append(pills, facts, note);
  }

  /* -- the brain --------------------------------------------------------- */
  {
    const body = card('What it has learned');
    const grid = document.createElement('div');
    grid.className = 'stat-grid';
    const stat = (value, label) => {
      const box = document.createElement('div');
      box.className = 'stat';
      const big = document.createElement('b');
      big.textContent = value;
      const small = document.createElement('span');
      small.textContent = label;
      box.append(big, small);
      grid.appendChild(box);
    };
    stat(data.reflex.rules_active, 'rules');
    stat(data.reflex.lessons, 'lessons');
    stat(data.reflex.skills, 'skills');
    stat(data.reflex.episodes, 'tasks');
    stat(data.reflex.signals, 'signals');
    stat(Math.round(data.reflex.success_rate * 100) + '%', 'succeeded');
    body.appendChild(grid);
  }

  /* -- tools ------------------------------------------------------------- */
  {
    const body = card('Tools · ' + data.tools.length);
    const pills = document.createElement('div');
    pills.className = 'pills';
    data.tools.forEach((tool) => {
      const pill = document.createElement('span');
      pill.className = 'pill';
      pill.dataset.risk = String(tool.risk);
      pill.textContent = tool.name;
      if (tool.description) pill.title = tool.description;
      pills.appendChild(pill);
    });
    body.appendChild(pills);

    if (data.skills.length) {
      const heading = document.createElement('p');
      heading.style.cssText = 'margin:12px 0 6px;font-size:12px;color:var(--ink-dim)';
      heading.textContent = 'Your skills';
      const skills = document.createElement('div');
      skills.className = 'pills';
      data.skills.forEach((skill) => {
        const pill = document.createElement('span');
        pill.className = 'pill';
        pill.textContent = skill.name;
        if (skill.description) pill.title = skill.description;
        skills.appendChild(pill);
      });
      body.append(heading, skills);
    }

    if (data.mcp.enabled && data.mcp.servers.length) {
      const heading = document.createElement('p');
      heading.style.cssText = 'margin:12px 0 6px;font-size:12px;color:var(--ink-dim)';
      heading.textContent = 'Connected servers';
      const servers = document.createElement('div');
      servers.className = 'pills';
      data.mcp.servers.forEach((name) => {
        const pill = document.createElement('span');
        pill.className = 'pill';
        pill.textContent = name;
        servers.appendChild(pill);
      });
      body.append(heading, servers);
    }
  }

  /* -- where things are -------------------------------------------------- */
  {
    const body = card('This machine');
    const facts = document.createElement('dl');
    facts.className = 'kv';
    row(facts, 'Version', data.app.version);
    row(facts, 'Python', data.app.python);
    row(facts, 'System', data.app.platform);
    row(facts, 'Project', data.paths.project);
    row(facts, 'Settings', data.paths.config);
    row(facts, 'Chats', data.paths.sessions);
    facts.querySelectorAll('dd').forEach((dd, index) => {
      if (index >= 3) dd.className = 'path';
    });
    body.appendChild(facts);
  }

  els.reflexBit.hidden = !data.reflex.rules_active;
  els.reflex.textContent = data.reflex.rules_active;
}

function refreshAdmin() {
  get('/api/admin').then((data) => { if (data) drawAdmin(data); });
}

function change(key, value) {
  post('/api/setting', { key, value }).then((reply) => {
    if (!reply.saved) {
      toast(reply.error || 'That did not take', 'bad', 'setting');
      refreshAdmin();
      return;
    }
    if (key === 'mode') { state.mode = value; drawMode(); }
    if (key === 'model') { state.model = value; drawWho(); }
    toast(key + ': ' + value, 'good', 'setting-' + key);
    refreshAdmin();
    get('/api/state').then(takeState);
  });
}

/* ------------------------------------------------------------------ theme */

const THEME_KEY = 'comodor-theme';

function applyTheme(choice) {
  const dark = choice === 'dark'
    || (choice !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  if (choice === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.dataset.theme = choice;
  $('theme-icon').firstElementChild.setAttribute('href', dark ? '#i-sun' : '#i-moon');
  $('theme').setAttribute('aria-label',
    dark ? 'Switch to the light theme' : 'Switch to the dark theme');
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', dark ? '#171615' : '#fbfaf8');
}

function readTheme() {
  try { return localStorage.getItem(THEME_KEY) || 'system'; } catch { return 'system'; }
}

applyTheme(readTheme());

$('theme').onclick = () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  const next = dark ? 'light' : 'dark';
  try { localStorage.setItem(THEME_KEY, next); } catch { /* private window */ }
  applyTheme(next);
};

matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (readTheme() === 'system') applyTheme('system');
});

/* ------------------------------------------------------------------- rail */

const RAIL_KEY = 'comodor-rail';
const narrow = () => matchMedia('(max-width: 900px)').matches;

function setRail(open) {
  els.shell.dataset.rail = open ? 'open' : 'closed';
  const toggle = $('rail-toggle');
  toggle.setAttribute('aria-expanded', String(open));
  toggle.setAttribute('aria-label', open ? 'Hide the chat list' : 'Show the chat list');
  if (!narrow()) {
    try { localStorage.setItem(RAIL_KEY, open ? 'open' : 'closed'); } catch { /* ignore */ }
  }
}

function closeRailIfNarrow() {
  if (narrow()) setRail(false);
}

setRail(narrow() ? false : (() => {
  try { return localStorage.getItem(RAIL_KEY) !== 'closed'; } catch { return true; }
})());

$('rail-toggle').onclick = () => setRail(els.shell.dataset.rail !== 'open');
els.scrim.onclick = () => setRail(false);
$('rail-close').onclick = () => setRail(false);

/* Tabs. Arrow keys move between them, which is what a tablist is expected to
 * do and what a keyboard user will try. */
const tabs = [$('tab-chat'), $('tab-admin')];

function selectTab(which) {
  tabs.forEach((tab) => {
    const on = tab === which;
    tab.setAttribute('aria-selected', String(on));
    tab.tabIndex = on ? 0 : -1;
    $(tab.getAttribute('aria-controls')).dataset.open = String(on);
  });
  if (which === tabs[1]) refreshAdmin();
}

tabs.forEach((tab, index) => {
  tab.onclick = () => selectTab(tab);
  tab.onkeydown = (event) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    event.preventDefault();
    const next = tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1))
      % tabs.length];
    selectTab(next);
    next.focus();
  };
});

$('admin-jump').onclick = () => {
  setRail(true);
  selectTab(tabs[1]);
};

/* ---------------------------------------------------------------- composer */

function grow() {
  els.prompt.style.height = 'auto';
  els.prompt.style.height = Math.min(els.prompt.scrollHeight,
    window.innerHeight * 0.34) + 'px';
}

els.prompt.addEventListener('input', () => {
  grow();
  orient(els.prompt, els.prompt.value);
});

els.prompt.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $('composer').requestSubmit();
  }
});

$('composer').addEventListener('submit', (event) => {
  event.preventDefault();
  const text = els.prompt.value.trim();
  if (!text || state.busy) return;
  els.prompt.value = '';
  els.prompt.removeAttribute('dir');
  grow();
  hideBlank();
  post('/api/send', { text }).then((reply) => {
    if (reply && reply.started === false) {
      toast(reply.error || 'Already working on something', 'bad', 'send');
    } else {
      refreshChats();
    }
  });
});

els.mode.onchange = () => change('mode', els.mode.value);
els.stop.onclick = () => post('/api/interrupt', {});

$('whoami').onclick = () => {
  setRail(true);
  selectTab(tabs[1]);
  setTimeout(() => {
    const pick = $('pick-model');
    if (pick) pick.focus();
  }, 60);
};

$('quit').onclick = () => {
  if (!confirm('End this session? Comodor stops on the machine it is running on.')) return;
  post('/api/quit', {}).then(() => {
    state.live = false;
    drawStatus();
    notice('Session ended. Comodor has stopped.');
  });
};

/* -------------------------------------------------------------- shortcuts */

document.addEventListener('keydown', (event) => {
  const typing = event.target === els.prompt || event.target === els.find;

  if (event.key === 'Escape') {
    if (state.busy) { post('/api/interrupt', {}); return; }
    if (narrow() && els.shell.dataset.rail === 'open') { setRail(false); return; }
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    setRail(true);
    selectTab(tabs[0]);
    els.find.focus();
    els.find.select();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'b') {
    event.preventDefault();
    setRail(els.shell.dataset.rail !== 'open');
    return;
  }
  if (!typing && event.key === '/' && !event.ctrlKey && !event.metaKey) {
    event.preventDefault();
    els.prompt.focus();
  }
});

let findTimer = 0;
els.find.addEventListener('input', () => {
  clearTimeout(findTimer);
  findTimer = setTimeout(refreshChats, 220);
});

$('new-chat').onclick = newChat;

/* ------------------------------------------------------------------- boot */

function takeState(data) {
  if (!data) return;
  state.provider = data.provider || state.provider;
  state.model = data.model || state.model;
  state.mode = data.mode || state.mode;
  state.project = data.project || state.project;
  state.cursor = data.cursor != null ? data.cursor : state.cursor;
  state.contextLimit = (data.context && data.context.limit) || state.contextLimit;
  state.chatId = (data.chat && data.chat.id) || state.chatId;
  if (data.usage) {
    state.usage.prompt = data.usage.prompt || 0;
    state.usage.output = data.usage.output || 0;
    state.usage.cost = data.usage.cost || 0;
  }
  setBusy(!!data.busy);
  drawWho();
  drawMode();
  drawStatus();
}

async function poll() {
  for (;;) {
    try {
      const response = await fetch('/api/events?cursor=' + state.cursor);
      if (response.status === 401) { location.reload(); return; }
      const data = await response.json();
      if (!state.live) { state.live = true; drawStatus(); }
      (data.events || []).forEach(apply);
      if (data.cursor) state.cursor = data.cursor;
      if (typeof data.busy === 'boolean' && data.busy !== state.busy) {
        setBusy(data.busy);
      }
    } catch {
      // The server went away, or something in between cut the connection.
      // Say so in the status strip and keep trying: reloading would lose the
      // scroll position and tell the reader nothing they did not know.
      if (state.live) { state.live = false; drawStatus(); }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  }
}

/**
 * What is on screen when the page opens, which is not one case but three.
 *
 *   Nothing has happened yet          -- the empty state.
 *   A session already running         -- replay the event log from the start,
 *                                        which is what it is kept for.
 *   A chat that was opened earlier    -- its transcript is on disk, not in the
 *                                        log, so read it and then listen from
 *                                        where that chat began.
 *
 * The cursor tells them apart: zero means the log holds this whole chat.
 */
get('/api/state').then((data) => {
  takeState(data);
  const chat = (data && data.chat) || {};

  if (!chat.messages) {
    showBlank();
    poll();
  } else if (state.cursor > 0) {
    post('/api/chat', { action: 'open', id: chat.id }).then((reply) => {
      drawTurns((reply && reply.turns) || []);
      poll();
    });
  } else {
    poll();                       // the log replays it
  }

  refreshChats();
  refreshAdmin();
  els.prompt.focus();
});
