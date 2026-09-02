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
  form: $('form'), formBack: $('form-back'),
};

const MODE_NOTE = {
  act: 'edits files and runs commands',
  plan: 'reads only — nothing is changed',
  ask: 'reads only — answers questions about the project',
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

/* ------------------------------------------------------------- mode change */

/*
 * A proposed mode change. Same dialog as a permission prompt — options are
 * buttons — but the choice is echoed into the composer's mode selector right
 * away, so what the page shows and what the session will do stay the same
 * thing while the agent is still reading the answer.
 */
function askMode(event) {
  els.ask.hidden = false;
  els.ask.textContent = '';

  const question = document.createElement('p');
  question.className = 'q bidi';
  question.id = 'ask-q';
  question.textContent = event.prompt || 'Change mode?';
  orient(question, question.textContent);
  els.ask.appendChild(question);

  const choices = document.createElement('div');
  choices.className = 'choices';
  const options = event.options && event.options.length
    ? event.options : [state.mode];
  options.forEach((option, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = option[0].toUpperCase() + option.slice(1);
    if (index === 0) button.className = 'primary';
    button.onclick = () => {
      els.ask.hidden = true;
      post('/api/answer', { id: event.id, choice: option });
      if (MODE_NOTE[option]) {
        state.mode = option;
        drawMode();
      }
    };
    choices.appendChild(button);
  });
  els.ask.appendChild(choices);
  const first = els.ask.querySelector('button');
  if (first) first.focus();
}

/* --------------------------------------------------------------- questions */
/*
 * The form the `ask` tool puts up. One dialog, one tab per question, and one
 * send.
 *
 * The state lives in `form` rather than being read back out of the DOM when
 * the user presses send. Reading it back would mean the checked attribute is
 * the record of what somebody answered, and the record would then be destroyed
 * every time a tab is redrawn.
 *
 * Answers are kept per question index: `chosen` is a Set of option indices,
 * `written` is whatever was typed into the last row. A single-answer question
 * clears one when the other is used, because the two together would be an
 * answer nobody gave.
 */

let form = null;

function askQuestions(event) {
  const questions = (event.questions || []).map(q => ({
    prompt: q.prompt || '',
    header: q.header || '',
    multi: !!q.multi,
    options: (q.options || []).map(o => ({
      label: o.label || '', why: o.description || '', free: !!o.free,
    })),
  }));
  if (!questions.length) return;

  form = {
    id: event.id,
    questions,
    at: 0,
    chosen: questions.map(() => new Set()),
    written: questions.map(() => ''),
    // What had focus before the dialog took it, so it can be given back.
    from: document.activeElement,
  };

  // The dialog takes the direction of the questions as a whole, which is what
  // decides the layout: which end the tab strip starts at, which side the
  // radio sits on, where the buttons go. Individual strings still decide their
  // own — a Persian question whose options name English packages keeps those
  // running left to right inside a right-to-left row.
  orient(els.form, questions.map(q => `${q.prompt} ${q.header}`).join(' '));

  els.formBack.hidden = false;
  els.form.hidden = false;
  drawForm();
  document.addEventListener('keydown', formKeys, true);
}

function formAnswered(index) {
  return form.chosen[index].size > 0 || form.written[index].trim() !== '';
}

function formGiven() {
  return form.questions.reduce((n, _, i) => n + (formAnswered(i) ? 1 : 0), 0);
}

function drawForm() {
  const many = form.questions.length > 1;
  const question = form.questions[form.at];

  $('form-title').textContent = many
    ? `${form.questions.length} questions`
    : 'One question';
  els.form.querySelector('.count').textContent = many
    ? `${formGiven()} of ${form.questions.length} answered`
    : '';

  drawTabs(many);
  drawBody(question);
  drawFoot();
}

function drawTabs(many) {
  const tabs = els.form.querySelector('.tabs');
  tabs.hidden = !many;
  tabs.textContent = '';
  if (!many) return;

  form.questions.forEach((question, index) => {
    const done = formAnswered(index);
    const tab = document.createElement('button');
    tab.type = 'button';
    tab.role = 'tab';
    tab.setAttribute('aria-selected', index === form.at ? 'true' : 'false');
    // The mark is a shape; the state has to reach a screen reader as words.
    tab.setAttribute('aria-label',
      `${question.header} — ${done ? 'answered' : 'not answered yet'}`);

    const mark = document.createElement('span');
    mark.className = done ? 'mark done' : 'mark';
    tab.appendChild(mark);

    const name = document.createElement('span');
    name.textContent = question.header;
    orient(name, question.header);
    tab.appendChild(name);

    tab.onclick = () => { form.at = index; drawForm(); };
    tabs.appendChild(tab);
  });
}

function drawBody(question) {
  const body = els.form.querySelector('.body');
  body.textContent = '';

  const prompt = document.createElement('p');
  prompt.className = 'prompt bidi';
  prompt.textContent = question.prompt;
  orient(prompt, question.prompt);
  body.appendChild(prompt);

  if (question.multi) {
    const note = document.createElement('p');
    note.className = 'note';
    note.textContent = 'Several answers may apply.';
    body.appendChild(note);
  }

  const list = document.createElement('div');
  list.className = 'options';
  list.role = question.multi ? 'group' : 'radiogroup';

  question.options.forEach((option, index) => {
    list.appendChild(drawOption(question, option, index));
    if (option.free) list.appendChild(drawOwn(option));
  });

  body.appendChild(list);
}

function drawOption(question, option, index) {
  const picked = option.free
    ? form.written[form.at].trim() !== ''
    : form.chosen[form.at].has(index);

  const row = document.createElement('button');
  row.type = 'button';
  row.className = 'option'
    + (question.multi ? ' many' : '')
    + (option.free ? ' free' : '');
  row.role = question.multi ? 'checkbox' : 'radio';
  row.setAttribute('aria-checked', picked ? 'true' : 'false');

  const box = document.createElement('span');
  box.className = 'box';
  row.appendChild(box);

  const text = document.createElement('span');
  text.className = 'text';

  const label = document.createElement('span');
  label.className = 'label bidi';
  label.textContent = option.label;
  orient(label, option.label);
  text.appendChild(label);

  if (option.why) {
    const why = document.createElement('span');
    why.className = 'why bidi';
    why.textContent = option.why;
    orient(why, option.why);
    text.appendChild(why);
  }

  row.appendChild(text);
  row.onclick = () => pickOption(index);
  return row;
}

function drawOwn(option) {
  const wrap = document.createElement('div');
  wrap.className = 'own';
  wrap.hidden = false;

  const box = document.createElement('textarea');
  box.rows = 2;
  box.placeholder = 'Type your answer';
  box.value = form.written[form.at];
  box.oninput = () => {
    form.written[form.at] = box.value;
    // Typing is answering: for a one-of question the listed options are no
    // longer the answer.
    if (!form.questions[form.at].multi && box.value.trim()) {
      form.chosen[form.at].clear();
    }
    orient(box, box.value);
    refreshForm();
  };
  // Enter sends the form only from a control that is not a text box. Here it
  // is a newline, because an answer somebody is writing out is often two
  // sentences.
  box.onkeydown = (e) => { if (e.key === 'Enter' && !e.metaKey && !e.ctrlKey) e.stopPropagation(); };
  orient(box, box.value);
  wrap.appendChild(box);
  void option;
  return wrap;
}

function pickOption(index) {
  const question = form.questions[form.at];
  const option = question.options[index];

  if (option.free) {
    const box = els.form.querySelector('.own textarea');
    if (box) box.focus();
    return;
  }
  if (question.multi) {
    const chosen = form.chosen[form.at];
    if (chosen.has(index)) chosen.delete(index); else chosen.add(index);
  } else {
    form.chosen[form.at] = new Set([index]);
    form.written[form.at] = '';
  }
  drawForm();
}

/* Redraws the parts that reflect progress without rebuilding the options —
 * rebuilding them while somebody is typing would take the caret away. */
function refreshForm() {
  const many = form.questions.length > 1;
  els.form.querySelector('.count').textContent = many
    ? `${formGiven()} of ${form.questions.length} answered`
    : '';
  if (many) drawTabs(true);
  const free = els.form.querySelector('.option.free');
  if (free) {
    free.setAttribute('aria-checked',
      form.written[form.at].trim() !== '' ? 'true' : 'false');
  }
  drawFoot();
}

function drawFoot() {
  const foot = els.form.querySelector('.foot');
  const keys = foot.querySelector('.keys');
  const skip = foot.querySelector('.skip');
  const send = foot.querySelector('.send');
  const given = formGiven();
  const total = form.questions.length;

  keys.textContent = '';
  if (total > 1) {
    keys.append('Move between questions with ');
    const left = document.createElement('kbd'); left.textContent = '←';
    const right = document.createElement('kbd'); right.textContent = '→';
    keys.append(left, ' ', right);
  }

  skip.textContent = 'Not now';
  skip.onclick = () => closeForm(true);

  send.className = given === total ? 'send' : 'send partial';
  send.textContent = given === total
    ? 'Send'
    : given === 0 ? 'Send with nothing chosen' : `Send ${given} of ${total}`;
  send.onclick = sendForm;
}

function formKeys(e) {
  if (!form) return;
  const typing = e.target && e.target.tagName === 'TEXTAREA';

  if (e.key === 'Escape') {
    if (typing) { e.target.blur(); e.stopPropagation(); return; }
    e.stopPropagation();
    closeForm(true);
    return;
  }
  if (typing) return;

  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    const step = e.key === 'ArrowRight' ? 1 : -1;
    form.at = (form.at + step + form.questions.length) % form.questions.length;
    e.preventDefault();
    drawForm();
    return;
  }
  if ((e.key === 'Enter' && (e.metaKey || e.ctrlKey))
      || (e.key === 'Enter' && document.activeElement === els.form)) {
    e.preventDefault();
    sendForm();
  }
}

function sendForm() {
  const answers = form.questions.map((question, index) => ({
    header: question.header,
    prompt: question.prompt,
    chosen: [...form.chosen[index]].sort((a, b) => a - b)
      .map(slot => question.options[slot].label),
    written: form.written[index].trim(),
  }));
  const id = form.id;
  closeForm(false);
  post('/api/answer', { id, choice: JSON.stringify(answers) });
}

function closeForm(dismissed) {
  const id = form ? form.id : null;
  const from = form ? form.from : null;
  document.removeEventListener('keydown', formKeys, true);
  els.form.hidden = true;
  els.formBack.hidden = true;
  form = null;
  if (dismissed && id) post('/api/answer', { id, choice: 'cancelled' });
  if (from && from.focus) from.focus();
}

/* -------------------------------------------------------------- local models */
/*
 * Models that live on this disk.
 *
 * The download is the part that shapes this. It is minutes to an hour, so it
 * cannot happen inside the request that starts it — the browser would hold an
 * open connection the whole time and any proxy in between would give up long
 * before it finished. The POST returns at once and the progress arrives on the
 * event stream the agent already uses, so the bar is drawn from events rather
 * than by asking over and over.
 *
 * Progress therefore updates one card in place. Redrawing the list on every
 * frame would rebuild the DOM twenty times a second and lose the scroll
 * position while somebody is reading the description of another model.
 */

const localState = { models: [], info: null, progress: {}, holder: null,
                     note: null, runtime: null };

function localCard(model) {
  const card = document.createElement('div');
  card.className = 'lm' + (model.active ? ' active' : '');
  card.dataset.model = model.id;

  const head = document.createElement('div');
  head.className = 'lm-head';

  const name = document.createElement('span');
  name.className = 'lm-name';
  name.textContent = model.name;
  head.appendChild(name);

  const facts = document.createElement('span');
  facts.className = 'lm-facts';
  const bits = [`${model.gigabytes} GB`];
  if (model.parameters) bits.push(model.parameters);
  if (model.quantization) bits.push(model.quantization);
  if (model.context) bits.push(`${(model.context / 1024).toFixed(0)}K context`);
  facts.textContent = bits.join(' · ');
  head.appendChild(facts);

  card.appendChild(head);

  if (model.description) {
    const why = document.createElement('p');
    why.className = 'lm-why bidi';
    why.textContent = model.description;
    orient(why, model.description);
    card.appendChild(why);
  }

  const tags = document.createElement('div');
  tags.className = 'lm-tags';
  if (model.tools) tags.appendChild(localTag('tools', 'can call tools'));
  if (model.vision) tags.appendChild(localTag('vision', 'reads images'));
  (model.good_at || []).forEach(g => tags.appendChild(localTag(g)));
  if (model.license) tags.appendChild(localTag(model.license, 'licence'));
  if (model.fits === false) tags.appendChild(localTag('too large', 'for this machine', 'bad'));
  if (tags.children.length) card.appendChild(tags);

  const bar = document.createElement('div');
  bar.className = 'lm-bar';
  bar.hidden = true;
  bar.innerHTML = '<div class="lm-track"><div class="lm-fill"></div></div>'
    + '<div class="lm-numbers"></div>';
  card.appendChild(bar);

  card.appendChild(localButtons(model));
  return card;
}

function localTag(text, title = '', kind = '') {
  const tag = document.createElement('span');
  tag.className = 'lm-tag' + (kind ? ' ' + kind : '');
  tag.textContent = text;
  if (title) tag.title = title;
  return tag;
}

function localButtons(model) {
  const row = document.createElement('div');
  row.className = 'lm-do';

  const busy = localState.progress[model.id]
    && !localState.progress[model.id].finished;

  if (busy) {
    row.appendChild(localButton('Stop', 'ghost', () =>
      localAct('cancel', model.id)));
    return row;
  }

  if (model.downloaded) {
    if (model.active) {
      const now = document.createElement('span');
      now.className = 'lm-now';
      now.textContent = 'In use';
      row.appendChild(now);
    } else {
      row.appendChild(localButton('Use this', 'primary', () =>
        localAct('use', model.id)));
    }
    row.appendChild(localButton('Delete', 'ghost', () => {
      if (confirm(`Delete ${model.name}? ${model.gigabytes} GB will be freed.`)) {
        localAct('remove', model.id);
      }
    }));
    return row;
  }

  const label = model.partial_bytes
    ? `Resume (${Math.round(model.partial_bytes / model.size * 100)}%)`
    : 'Download';
  const get = localButton(label, 'primary', () => localAct('get', model.id));
  if (model.room === false) {
    get.disabled = true;
    get.title = 'not enough room on this disk';
  }
  row.appendChild(get);
  return row;
}

function localButton(text, kind, onclick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = kind;
  button.textContent = text;
  button.onclick = onclick;
  return button;
}

/* Only the one card that is moving, so the rest of the list holds still. */
function localProgress(event) {
  const at = localState.progress[event.model] || (localState.progress[event.model] = {});
  Object.assign(at, event);

  const card = localState.holder && localState.holder.querySelector(`[data-model="${event.model}"]`);
  if (!card) return;

  const bar = card.querySelector('.lm-bar');
  const fill = card.querySelector('.lm-fill');
  const numbers = card.querySelector('.lm-numbers');

  if (event.failed) {
    bar.hidden = true;
    notice(`${event.name}: ${event.error}`, true);
    delete localState.progress[event.model];
    loadLocal();
    return;
  }
  if (event.finished) {
    bar.hidden = true;
    notice(`${event.name} downloaded and verified.`);
    delete localState.progress[event.model];
    loadLocal();
    return;
  }

  bar.hidden = false;
  fill.style.width = `${event.percent || 0}%`;

  const parts = [`${(event.percent || 0).toFixed(1)}%`];
  if (event.done_bytes != null && event.total) {
    parts.push(`${humanBytes(event.done_bytes)} of ${humanBytes(event.total)}`);
  }
  if (event.bytes_per_second) parts.push(`${humanBytes(event.bytes_per_second)}/s`);
  if (event.seconds_left != null) parts.push(`${humanTime(event.seconds_left)} left`);
  if (event.resumed) parts.push('resumed');
  numbers.textContent = parts.join('  ·  ');

  const stop = card.querySelector('.lm-do button');
  if (stop && stop.textContent !== 'Stop') card.replaceChild(
    localButtons({ ...localState.models.find(m => m.id === event.model), busy: true }),
    card.querySelector('.lm-do'));
}

function humanBytes(n) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return i === 0 ? `${n.toFixed(0)} B` : `${n.toFixed(1)} ${units[i]}`;
}

function humanTime(seconds) {
  seconds = Math.round(seconds);
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`;
  return `${Math.floor(seconds / 3600)}h ${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}m`;
}

async function localAct(action, model) {
  const answer = await post('/api/local', { action, model });
  if (!answer || answer.ok === false) {
    notice((answer && answer.error) || 'that did not work', true);
    return;
  }
  if (action === 'get') {
    localState.progress[model] = { percent: 0 };
    const card = localState.holder.querySelector(`[data-model="${model}"]`);
    if (card) card.querySelector('.lm-bar').hidden = false;
  }
  if (action !== 'get') loadLocal();
}

async function loadLocal() {
  if (!localState.holder) return;
  const data = await get('/api/local');
  if (!data) return;
  localState.models = data.models || [];
  localState.info = data;

  localState.holder.textContent = '';
  if (!data.ok) {
    notice(data.error || 'the model list could not be read', true);
    return;
  }
  localState.models.forEach(m => localState.holder.appendChild(localCard(m)));

  if (localState.note) {
    const bits = [];
    if (data.memory_gb) bits.push(`${data.memory_gb} GB of memory`);
    if (data.free_bytes) bits.push(`${humanBytes(data.free_bytes)} free`);
    if (data.used_bytes) bits.push(`${humanBytes(data.used_bytes)} used by models`);
    bits.push(`list from ${data.source}`);
    localState.note.textContent = bits.join(' · ');
  }

  if (localState.runtime) {
    localState.runtime.hidden = !!data.runtime;
  }
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
    case 'notice':
      // A download reports here rather than on a channel of its own: it is a
      // stream of small updates about something the user started, which is
      // what this channel already is. `what` says which shape it is — not
      // `kind`, which the frame stamps with the event's own kind and would
      // silently overwrite.
      if (event.what === 'download') localProgress(event);
      else notice(event.text);
      break;
    case 'error': endStream(); notice(event.text, true); break;
    case 'cancelled': endStream(); notice('Stopped.'); break;
    case 'request':
      if (event.about === 'questions') askQuestions(event);
      else if (event.about === 'mode') askMode(event);
      else askFor(event);
      break;
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
  // Nothing chosen yet is not "— › —", which reads as something that failed
  // to load. The breadcrumb is about which model is answering, and until one
  // is picked there is no answer to give.
  const known = Boolean(state.model);
  $('whoami').hidden = !known;
  els.whoProvider.textContent = state.provider || '';
  els.whoModel.textContent = state.model || '';
  document.title = known ? 'Comodor · ' + state.model : 'Comodor';
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

    // Only a title that is actually cut off gets the fade. Measured after
    // it is in the document, because the answer depends on the font, the
    // language and how wide the rail has been dragged to.
    requestAnimationFrame(() => {
      title.dataset.clipped = String(title.scrollWidth > title.clientWidth + 1);
    });

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

/* ------------------------------------------------------------- setting up
 *
 * Shown in place of the conversation, because there is no conversation to
 * have until this is answered.
 */

let chosen = null;

function drawSetup(offer) {
  const box = $('setup');
  box.hidden = false;
  box.textContent = '';

  const sheet = document.createElement('div');
  sheet.className = 'sheet';

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'mark');
  svg.setAttribute('viewBox', '0 0 512 512');
  svg.setAttribute('fill', 'var(--accent)');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#i-mark');
  svg.appendChild(use);

  const head = document.createElement('h1');
  head.textContent = 'Which model should answer?';
  const sub = document.createElement('p');
  sub.className = 'sub';
  sub.textContent = 'Asked once. The answer is saved to ' + offer.config_file
    + ', and you can change it later in Admin.';
  sheet.append(svg, head, sub);

  // What the machine already has, above the list of billing pages. For
  // somebody with Ollama running, or a key already exported, the list is the
  // wrong first question: the answer is here and nobody asked it.
  const here = new Map((offer.running || []).map((item) => [item.provider, item]));
  const exported = new Map((offer.exported || []).map((item) => [item.provider, item]));
  const ordered = [
    ...offer.providers.filter((e) => here.has(e.id) || exported.has(e.id)),
    ...offer.providers.filter((e) => !here.has(e.id) && !exported.has(e.id)),
  ];

  if (here.size || exported.size) {
    const lead = document.createElement('p');
    lead.className = 'found';
    lead.textContent = 'Already on this machine — nothing to sign up for:';
    sheet.appendChild(lead);
  }

  const grid = document.createElement('div');
  grid.className = 'providers';
  ordered.forEach((entry) => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'provider';
    card.setAttribute('aria-pressed', String(chosen === entry.id));
    const name = document.createElement('b');
    name.textContent = entry.label;
    const what = document.createElement('span');
    what.textContent = entry.blurb;
    card.append(name, what);
    // What was found about it outranks what the catalogue says: "running
    // here, three models" is the answer, and the sales line is what you read
    // when there is no answer yet.
    const found = here.get(entry.id);
    const held = exported.get(entry.id);
    if (found) {
      what.textContent = found.usable ? found.summary
        : 'running here, but no models are installed yet';
      card.classList.add('here');
    }
    if (found && found.usable) {
      const up = document.createElement('em');
      up.textContent = 'running here';
      card.appendChild(up);
    } else if (held) {
      const key = document.createElement('em');
      key.textContent = 'key already in $' + held.variable;
      card.appendChild(key);
    } else if (!entry.needs_key) {
      const free = document.createElement('em');
      free.textContent = 'no key needed';
      card.appendChild(free);
    }
    card.onclick = () => {
      chosen = entry.id;
      drawSetup(offer);
      // Eighteen providers is more than a screen, so the form for the one
      // just chosen is below the fold — and a form nobody can see reads as a
      // click that did nothing.
      const form = $('setup').querySelector('.form');
      if (form) form.scrollIntoView({ block: 'center', behavior: 'smooth' });
    };
    grid.appendChild(card);
  });
  sheet.appendChild(grid);

  const entry = offer.providers.find((item) => item.id === chosen);
  if (entry) sheet.appendChild(setupForm(offer, entry));

  box.appendChild(sheet);
}

//: Which way the person said they want to connect, per provider.
let connectVia = '';
let signInPoll = 0;

function setupForm(offer, entry) {
  const form = document.createElement('form');
  form.className = 'form';

  const needsSomething = entry.needs_key;
  const canSignIn = entry.can_sign_in && offer.may_enter_a_key;

  // Where a provider offers both, how to connect is a real question. Where it
  // offers one, asking would be a question with one answer.
  if (needsSomething && canSignIn) {
    if (!connectVia) connectVia = 'signin';
    const choice = document.createElement('div');
    choice.className = 'how';
    [['signin', 'Sign in with ' + entry.label,
      'Opens ' + entry.label + ' in your browser and brings a key back. '
      + 'Nothing to find, nothing to paste.'],
     ['key', 'Paste an API key',
      'If you already have one, or it comes from somewhere else.']
    ].forEach(([value, title, note]) => {
      const option = document.createElement('button');
      option.type = 'button';
      option.className = 'how-option';
      option.setAttribute('aria-pressed', String(connectVia === value));
      const name = document.createElement('b');
      name.textContent = title;
      const what = document.createElement('span');
      what.textContent = note;
      option.append(name, what);
      option.onclick = () => { connectVia = value; drawSetup(offer); };
      choice.appendChild(option);
    });
    form.appendChild(choice);
  } else if (needsSomething) {
    connectVia = 'key';
  } else {
    connectVia = 'none';
  }

  // A key cannot be taken safely here, so the box is not drawn. A warning
  // beside a field is a warning next to a field somebody fills in anyway.
  if (needsSomething && !offer.may_enter_a_key) {
    const blocked = document.createElement('div');
    blocked.className = 'blocked';
    const why = document.createElement('p');
    why.textContent = 'This page reached you across a network, and there is no '
      + 'TLS here — a key typed in, or signed in for, would cross that network '
      + 'in the clear. Two ways to do it safely:';
    const how = document.createElement('pre');
    how.textContent = '# on the machine Comodor is running on\n'
      + 'comodor setup\n\n'
      + '# or bring the page to you through an SSH tunnel\n'
      + `ssh -N -L ${offer.port}:127.0.0.1:${offer.port} you@host`;
    blocked.append(why, how);
    form.appendChild(blocked);
    return form;
  }

  let key = null;
  if (connectVia === 'key') {
    const line = document.createElement('label');
    line.className = 'line';
    line.append(document.createTextNode(`${entry.label} API key`));
    key = document.createElement('input');
    key.type = 'password';
    key.className = 'mono';
    key.autocomplete = 'off';
    key.spellcheck = false;
    key.placeholder = 'paste it here';
    line.appendChild(key);
    if (entry.keys_url) {
      const aside = document.createElement('span');
      aside.className = 'aside';
      aside.append(document.createTextNode('Get one at '));
      const link = document.createElement('a');
      link.href = entry.keys_url;
      link.target = '_blank';
      link.rel = 'noreferrer noopener';
      link.textContent = entry.keys_url.replace(/^https?:\/\//, '');
      aside.appendChild(link);
      line.appendChild(aside);
    }
    form.appendChild(line);
  }

  const line = document.createElement('label');
  line.className = 'line';
  line.append(document.createTextNode('Model'));
  let picked = entry.model || '';
  const combo = modelCombo(picked, (id) => { picked = id; });
  line.appendChild(combo);
  form.appendChild(line);
  loadModels(entry.id, false);

  let url = null;
  if (!entry.base_url) {
    const where = document.createElement('label');
    where.className = 'line';
    where.append(document.createTextNode('Endpoint URL'));
    url = document.createElement('input');
    url.type = 'url';
    url.className = 'mono';
    url.placeholder = 'https://…/v1';
    where.appendChild(url);
    form.appendChild(where);
  }

  const go = document.createElement('button');
  go.type = 'submit';
  go.className = 'go';
  go.textContent = connectVia === 'signin'
    ? 'Sign in with ' + entry.label : 'Save and start';
  form.appendChild(go);

  form.onsubmit = (event) => {
    event.preventDefault();
    if (connectVia === 'signin') { signIn(entry, form, go); return; }
    go.disabled = true;
    go.textContent = 'Saving…';
    post('/api/setup', {
      provider: entry.id,
      api_key: key ? key.value : '',
      model: picked,
      base_url: url ? url.value : '',
    }).then((reply) => {
      go.disabled = false;
      go.textContent = 'Save and start';
      if (!reply.ok) { toast(reply.error || 'That did not take', 'bad', 'setup'); return; }
      settledIn(reply.state);
    });
  };
  return form;
}

/* -- signing in -------------------------------------------------------------
 *
 * Two shapes, decided by whether a loopback port could be taken. With one, the
 * browser comes back on its own and this only has to wait. Without one — over
 * SSH, in a container — the page shows a code and it is pasted back.
 */

function signIn(entry, form, go) {
  go.disabled = true;
  go.textContent = 'Opening ' + entry.label + '…';

  post('/api/signin', { step: 'start', provider: entry.id, browser: true })
    .then((reply) => {
      go.disabled = false;
      go.textContent = 'Sign in with ' + entry.label;
      if (!reply.ok) { toast(reply.error || 'Could not start', 'bad', 'signin'); return; }

      window.open(reply.url, '_blank', 'noopener');
      drawWaiting(entry, form, reply);
    });
}

function drawWaiting(entry, form, reply) {
  const box = document.createElement('div');
  box.className = 'waiting';

  const said = document.createElement('p');
  said.textContent = reply.paste_the_code
    ? entry.label + ' will show you a code. Paste it here.'
    : 'Waiting for ' + entry.label + ' — approve it in the tab that opened.';
  box.appendChild(said);

  const again = document.createElement('a');
  again.href = reply.url;
  again.target = '_blank';
  again.rel = 'noreferrer noopener';
  again.className = 'aside';
  again.textContent = 'The tab did not open? Use this link.';
  box.appendChild(again);

  if (reply.paste_the_code) {
    const row = document.createElement('div');
    row.className = 'key-row';
    const code = document.createElement('input');
    code.type = 'text';
    code.className = 'mono';
    code.placeholder = 'paste the code';
    code.setAttribute('aria-label', 'The code ' + entry.label + ' showed you');
    const send = document.createElement('button');
    send.type = 'button';
    send.className = 'small primary';
    send.textContent = 'Finish';
    send.onclick = () => finishSignIn(code.value, box);
    row.append(code, send);
    box.appendChild(row);
    code.focus();
  } else {
    clearInterval(signInPoll);
    signInPoll = setInterval(() => {
      get('/api/signin').then((state) => {
        if (!state) return;
        if (state.ready) { clearInterval(signInPoll); finishSignIn('', box); }
        else if (state.error) {
          clearInterval(signInPoll);
          said.textContent = state.error;
          said.className = 'warn';
        }
      });
    }, 1200);
  }

  const stop = document.createElement('button');
  stop.type = 'button';
  stop.className = 'small';
  stop.textContent = 'Cancel';
  stop.onclick = () => { clearInterval(signInPoll); box.remove(); };
  box.appendChild(stop);

  form.appendChild(box);
  box.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function finishSignIn(code, box) {
  post('/api/signin', { step: 'finish', code }).then((reply) => {
    if (!reply.ok) { toast(reply.error || 'That did not complete', 'bad', 'signin'); return; }
    clearInterval(signInPoll);
    box.remove();
    settledIn(reply.state);
  });
}

function settledIn(state) {
  $('setup').hidden = true;
  takeState(state);
  showBlank();
  refreshAdmin();
  toast('Ready — ' + (state.model || 'set up'), 'good', 'setup');
  els.prompt.focus();
}

function askForSetup() {
  els.prompt.disabled = true;
  els.prompt.placeholder = 'Choose a model first';
  get('/api/setup').then((offer) => {
    if (!offer) return;
    // Nothing is preselected. `ready` is true for a local provider by
    // definition — it needs no key — so choosing the first ready one put
    // Ollama in front of somebody who has never run it, and the highlighted
    // card is read as a recommendation.
    chosen = null;
    drawSetup(offer);
  });
}

/* ------------------------------------------------------------------ rules
 *
 * A rule is a standing instruction to the agent, and there are two kinds in
 * one list. What you wrote is obeyed from the first time. What the agent
 * noticed is obeyed once there is enough evidence, and carries that evidence
 * as a count — a claim about how somebody works should be checkable rather
 * than asserted.
 *
 * Yours sort first. Burying an instruction under forty inferences reads as the
 * agent having opinions of its own.
 */

function icon(name, size) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', name);
  svg.appendChild(use);
  if (size) { svg.style.width = size; svg.style.height = size; }
  return svg;
}

function ruleAction(action, id, then) {
  post('/api/rules', { action, id }).then((reply) => {
    if (!reply.ok) { toast(reply.error || 'That did not take', 'bad', 'rule'); return; }
    if (then) toast(then, 'good', 'rule');
    refreshRules();
    refreshAdmin();
  });
}

function drawRules(data) {
  const body = $('rules-body');
  body.textContent = '';

  if (!data.enabled) {
    const off = document.createElement('p');
    off.className = 'empty-note';
    off.textContent = 'Rules are switched off in your settings, so nothing '
      + 'here is being applied.';
    body.appendChild(off);
  }

  const lead = document.createElement('div');
  lead.className = 'lead';
  const count = document.createElement('span');
  count.className = 'count';
  count.textContent = data.rules.length
    ? `${data.active} in force of ${data.rules.length}`
    : 'No rules yet';
  lead.appendChild(count);

  if (data.rules.length) {
    const out = document.createElement('button');
    out.type = 'button';
    out.title = 'Write them to .comodor/house-rules.md';
    out.append(icon('#i-export'), document.createTextNode('Export'));
    out.onclick = () => post('/api/rules', { action: 'export' }).then((reply) => {
      toast(reply.ok ? 'Written to ' + reply.path
                     : (reply.error || 'Could not write them'),
            reply.ok ? 'good' : 'bad', 'rule');
    });
    lead.appendChild(out);
  }
  body.appendChild(lead);

  if (!data.rules.length) {
    const note = document.createElement('p');
    note.className = 'empty-note';
    note.style.textAlign = 'start';
    note.textContent = 'Write one above and it applies from the next message. '
      + 'Comodor also watches how this project is written and what you change '
      + 'about its output, and proposes rules of its own once there is enough '
      + 'evidence — those show their working.';
    body.appendChild(note);
    return;
  }

  data.rules.forEach((rule) => {
    const box = document.createElement('article');
    box.className = 'rule';
    box.dataset.mine = String(rule.mine);
    box.dataset.active = String(rule.active);
    box.dataset.confident = String(rule.confident);

    const said = document.createElement('p');
    said.className = 'statement bidi';
    said.style.margin = '0';
    said.textContent = rule.statement;
    orient(said, rule.statement);
    box.appendChild(said);

    const evidence = document.createElement('div');
    evidence.className = 'evidence';
    if (rule.mine) {
      const who = document.createElement('span');
      who.textContent = 'you wrote this';
      evidence.appendChild(who);
    } else {
      // The count and the bar say the same thing twice on purpose: the
      // fraction is the claim and the bar is how strong it is at a glance.
      const bar = document.createElement('span');
      bar.className = 'bar';
      const fill = document.createElement('i');
      fill.style.width = Math.round(rule.strength * 100) + '%';
      bar.appendChild(fill);
      const seen = document.createElement('span');
      const total = rule.support + rule.against;
      seen.textContent = total
        ? `${rule.support} of ${total} times` : 'not seen yet';
      evidence.append(bar, seen);
      if (!rule.confident) {
        const waiting = document.createElement('span');
        waiting.textContent = '· still gathering evidence';
        evidence.appendChild(waiting);
      }
    }
    if (rule.detail && !rule.mine) {
      const why = document.createElement('span');
      why.textContent = '· ' + rule.detail;
      why.style.overflow = 'hidden';
      why.style.textOverflow = 'ellipsis';
      evidence.appendChild(why);
    }
    box.appendChild(evidence);

    const doings = document.createElement('div');
    doings.className = 'doings';

    const onoff = document.createElement('button');
    onoff.type = 'button';
    onoff.title = rule.active ? 'Switch this rule off' : 'Switch it back on';
    if (!rule.active) onoff.style.color = 'var(--good)';
    onoff.setAttribute('aria-label', onoff.title);
    onoff.appendChild(icon(rule.active ? '#i-off' : '#i-on'));
    onoff.onclick = () => ruleAction(rule.active ? 'disable' : 'enable', rule.id,
                                     rule.active ? 'Rule switched off'
                                                 : 'Rule switched on');

    const pin = document.createElement('button');
    pin.type = 'button';
    pin.title = rule.pinned ? 'Stop always applying this' : 'Always apply this';
    pin.setAttribute('aria-label', pin.title);
    pin.setAttribute('aria-pressed', String(rule.pinned));
    pin.appendChild(icon('#i-pin'));
    pin.onclick = () => ruleAction(rule.pinned ? 'unpin' : 'pin', rule.id,
                                   rule.pinned ? 'No longer pinned' : 'Pinned');

    const drop = document.createElement('button');
    drop.type = 'button';
    drop.className = 'drop';
    drop.title = 'Delete this rule';
    drop.setAttribute('aria-label', 'Delete this rule');
    drop.appendChild(icon('#i-trash'));
    drop.onclick = () => {
      if (!confirm('Delete this rule? Switching it off keeps it for later.')) return;
      ruleAction('forget', rule.id, 'Rule deleted');
    };

    const spacer = document.createElement('span');
    spacer.className = 'spacer';
    const where = document.createElement('span');
    where.className = 'where';
    where.textContent = rule.scope === 'global' ? 'everywhere' : 'this project';

    doings.append(onoff, pin, drop, spacer, where);
    box.appendChild(doings);
    body.appendChild(box);
  });
}

function refreshRules() {
  get('/api/rules').then((data) => { if (data) drawRules(data); });
  refreshFacts();
}

/* -- curated memory ----------------------------------------------------------
 *
 * One-sentence facts the agent maintains about this project and this person.
 * Staged proposals — the background review's suggestions under write approval
 * — show dashed until they are approved or rejected.
 */
function factAction(action, id, then) {
  post('/api/facts', { action, id }).then((reply) => {
    if (!reply.ok) { toast(reply.error || 'That did not take', 'bad', 'rule'); return; }
    if (then) toast(then, 'good', 'rule');
    refreshFacts();
    refreshAdmin();
  });
}

function drawFacts(data) {
  const body = $('facts-body');
  body.textContent = '';

  if (!data.enabled) {
    const off = document.createElement('p');
    off.className = 'empty-note';
    off.textContent = 'The background review is switched off in your '
      + 'settings, so nothing is being proposed here. Facts you write below '
      + 'still apply.';
    body.appendChild(off);
  }

  if (!data.facts.length) {
    const note = document.createElement('p');
    note.className = 'empty-note';
    note.style.textAlign = 'start';
    note.textContent = 'Nothing here yet. The shelves are small on purpose: '
      + data.usage + '.';
    body.appendChild(note);
    return;
  }

  const lead = document.createElement('p');
  lead.className = 'empty-note';
  lead.style.textAlign = 'start';
  lead.textContent = data.usage;
  body.appendChild(lead);

  data.facts.forEach((fact) => {
    const box = document.createElement('article');
    box.className = 'fact';
    box.dataset.staged = String(fact.staged);

    const said = document.createElement('p');
    const kind = document.createElement('span');
    kind.className = 'kind';
    kind.textContent = fact.staged ? 'proposed' : fact.kind
      + (fact.pinned ? ' · pinned' : '');
    said.appendChild(kind);
    said.appendChild(document.createTextNode(fact.text));
    box.appendChild(said);

    const doings = document.createElement('div');
    doings.className = 'doings';
    const act = (action, label, then) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.onclick = () => factAction(action, fact.id, then);
      doings.appendChild(button);
    };
    if (fact.staged) {
      act('approve', 'Approve', 'Fact approved — it applies from your next session');
      act('reject', 'Reject', 'Proposal discarded');
    } else {
      act(fact.pinned ? 'unpin' : 'pin', fact.pinned ? 'Unpin' : 'Pin');
    }
    act('remove', 'Remove');
    box.appendChild(doings);
    body.appendChild(box);
  });
}

function refreshFacts() {
  get('/api/facts').then((data) => { if (data) drawFacts(data); });
}

$('fact-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const field = $('fact-text');
  const text = field.value.trim();
  if (!text) return;
  post('/api/facts', { action: 'add', text, kind: 'memory' }).then((reply) => {
    if (!reply.ok) { toast(reply.error || 'That did not take', 'bad', 'rule'); return; }
    field.value = '';
    toast('Fact added — it applies from your next session', 'good', 'rule');
    refreshFacts();
    refreshAdmin();
  });
});

$('rule-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const field = $('rule-text');
  const statement = field.value.trim();
  if (!statement) return;
  post('/api/rules', { action: 'teach', statement }).then((reply) => {
    if (!reply.ok) { toast(reply.error || 'That did not take', 'bad', 'rule'); return; }
    field.value = '';
    field.removeAttribute('dir');
    toast('Rule added — it applies from your next message', 'good', 'rule');
    refreshRules();
    refreshAdmin();
  });
});

$('rule-text').addEventListener('input', () => {
  orient($('rule-text'), $('rule-text').value);
});

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

function field(parent, label, control, note, noteClass) {
  const line = document.createElement('label');
  line.className = 'control';
  const name = document.createElement('span');
  name.className = 'label';
  name.textContent = label;
  line.append(name, control);
  if (note) {
    const aside = document.createElement('span');
    aside.className = 'aside' + (noteClass ? ' ' + noteClass : '');
    aside.textContent = note;
    if (noteClass === 'path') aside.title = note;
    line.appendChild(aside);
  }
  parent.appendChild(line);
  return control;
}

function money(value) {
  if (value === null || value === undefined) return 'price not stated';
  if (value === 0) return 'free';
  return '$' + (value < 1 ? value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')
                          : value.toFixed(2)) + '/M';
}

/* -- choosing from four hundred models --------------------------------------
 *
 * A combobox, not a `<select>` and not a permanent list: four hundred rows is
 * too many to scroll and too many to render until somebody asks. It opens on
 * demand, filters as you type, and moves with the arrow keys.
 *
 * One function, used by the setup screen and by Admin. Two pickers for the
 * same job drift, and then only one of them gets the fix.
 */

let modelIndex = { provider: '', models: [], source: '', age: 0, error: '' };
window.modelIndex = modelIndex;

function tokens(n) {
  if (!n) return '';
  if (n >= 1000000) return (n / 1000000).toFixed(n % 1000000 ? 1 : 0) + 'M';
  if (n >= 1000) return Math.round(n / 1000) + 'K';
  return String(n);
}

function money(value) {
  if (value === null || value === undefined) return null;
  if (value === 0) return 'free';
  return '$' + (value < 1 ? String(Number(value.toFixed(3))) : value.toFixed(2)) + '/M';
}

function ago(seconds) {
  if (!seconds) return 'just now';
  if (seconds < 90) return 'a moment ago';
  if (seconds < 5400) return Math.round(seconds / 60) + ' minutes ago';
  if (seconds < 172800) return Math.round(seconds / 3600) + ' hours ago';
  return Math.round(seconds / 86400) + ' days ago';
}

/**
 * @param onPick   called with the chosen model id
 * @param current  the id to show when closed
 */
function modelCombo(current, onPick) {
  const wrap = document.createElement('div');
  wrap.className = 'combo';

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'combo-button';
  button.setAttribute('aria-haspopup', 'listbox');
  button.setAttribute('aria-expanded', 'false');

  const shown = document.createElement('span');
  shown.className = 'mono';
  const caret = document.createElement('span');
  caret.className = 'combo-caret';
  button.append(shown, caret);

  const panel = document.createElement('div');
  panel.className = 'combo-panel';
  panel.hidden = true;

  const search = document.createElement('input');
  search.type = 'text';
  search.className = 'combo-search';
  search.placeholder = 'Search models';
  search.setAttribute('aria-label', 'Search models');
  search.spellcheck = false;

  const list = document.createElement('div');
  list.className = 'combo-list';
  list.setAttribute('role', 'listbox');

  const status = document.createElement('div');
  status.className = 'combo-status';

  panel.append(search, list, status);
  wrap.append(button, panel);

  let chosenId = current;
  let cursor = 0;
  let visible = [];

  const label = () => {
    shown.textContent = chosenId || 'choose a model';
    shown.classList.toggle('placeholder', !chosenId);
  };

  const drawStatus = () => {
    status.textContent = '';
    const count = document.createElement('span');
    count.textContent = modelIndex.models.length
      ? `${modelIndex.models.length} models` : 'no list yet';
    const where = document.createElement('span');
    if (modelIndex.source === 'live') where.textContent = 'from the provider';
    else if (modelIndex.source === 'cached') where.textContent = 'checked ' + ago(modelIndex.age);
    else if (modelIndex.source === 'stale') {
      where.textContent = 'checked ' + ago(modelIndex.age) + ', provider unreachable';
      where.className = 'warn';
    } else {
      where.textContent = modelIndex.error
        ? 'built-in list — ' + modelIndex.error : 'built-in list';
      where.className = 'warn';
    }
    const again = document.createElement('button');
    again.type = 'button';
    again.textContent = 'Refresh';
    again.onclick = (event) => {
      event.stopPropagation();
      loadModels(modelIndex.provider, true);
    };
    status.append(count, where, again);
  };

  const draw = () => {
    const needle = search.value.trim().toLowerCase();
    visible = modelIndex.models.filter(
      (m) => !needle || m.id.toLowerCase().includes(needle)
             || (m.name || '').toLowerCase().includes(needle));
    // Alphabetical, with the one in use lifted to the top so it is where the
    // eye already is rather than wherever the alphabet put it.
    const here = visible.findIndex((m) => m.id === chosenId);
    if (here > 0) visible.unshift(visible.splice(here, 1)[0]);

    list.textContent = '';
    if (!visible.length) {
      const none = document.createElement('p');
      none.className = 'combo-empty';
      none.textContent = modelIndex.models.length
        ? 'Nothing matches that.' : 'No models to choose from yet.';
      list.appendChild(none);
      drawStatus();
      return;
    }
    if (cursor >= visible.length) cursor = 0;

    visible.slice(0, 200).forEach((model, index) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'combo-row';
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(model.id === chosenId));
      if (index === cursor) row.dataset.cursor = 'true';
      if (model.tools === false) row.dataset.noTools = 'true';

      const id = document.createElement('b');
      id.textContent = model.id;

      const facts = document.createElement('span');
      const bits = [];
      if (model.context) bits.push(tokens(model.context) + ' ctx');
      if (model.max_output) bits.push(tokens(model.max_output) + ' out');
      const inCost = money(model.input_cost);
      const outCost = money(model.output_cost);
      if (inCost === 'free' && outCost === 'free') bits.push('free');
      else {
        if (inCost) bits.push(inCost + ' in');
        if (outCost) bits.push(outCost + ' out');
      }
      facts.textContent = bits.join('  ·  ');

      row.append(id, facts);

      const marks = document.createElement('span');
      marks.className = 'combo-marks';
      if (model.tools === false) {
        const no = document.createElement('em');
        no.className = 'bad';
        no.textContent = 'no tools';
        no.title = 'This model cannot call tools, so Comodor could not read or '
          + 'edit files with it.';
        marks.appendChild(no);
      }
      if (model.vision) {
        const eye = document.createElement('em');
        eye.textContent = 'vision';
        eye.title = 'Can be shown images — needed for screen control.';
        marks.appendChild(eye);
      }
      if (marks.childElementCount) row.appendChild(marks);

      row.onclick = () => {
        chosenId = model.id;
        label();
        close();
        onPick(model.id);
      };
      list.appendChild(row);
    });

    if (visible.length > 200) {
      const more = document.createElement('p');
      more.className = 'combo-empty';
      more.textContent = `${visible.length - 200} more — type to narrow`;
      list.appendChild(more);
    }
    drawStatus();
  };

  const scrollToCursor = () => {
    const row = list.querySelector('[data-cursor="true"]');
    if (row) row.scrollIntoView({ block: 'nearest' });
  };

  // Where the panel goes, given where the button ended up. Below when there
  // is room, above when there is not — in the rail the model card sits near
  // the bottom, and a panel that always opens downward opens off the screen.
  const place = () => {
    const box = button.getBoundingClientRect();
    if (box.bottom < 0 || box.top > window.innerHeight) { close(); return; }
    const below = window.innerHeight - box.bottom - 12;
    const above = box.top - 12;
    const room = Math.max(below, above);
    const height = Math.min(340, Math.max(180, room));
    panel.style.left = box.left + 'px';
    panel.style.width = box.width + 'px';
    panel.style.height = height + 'px';
    if (below >= height || below >= above) {
      panel.style.top = (box.bottom + 4) + 'px';
      panel.style.bottom = 'auto';
    } else {
      panel.style.top = (box.top - height - 4) + 'px';
      panel.style.bottom = 'auto';
    }
  };

  const open = () => {
    panel.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    cursor = 0;
    draw();
    place();
    search.focus();
    search.select();
    // `true` so it fires for any ancestor that scrolls, not only the window.
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
  };

  const close = () => {
    panel.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    search.value = '';
    window.removeEventListener('scroll', place, true);
    window.removeEventListener('resize', place);
  };

  button.onclick = () => (panel.hidden ? open() : close());

  search.addEventListener('input', () => { cursor = 0; draw(); });
  search.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { close(); button.focus(); return; }
    if (event.key === 'Enter') {
      event.preventDefault();
      const model = visible[cursor];
      if (model) {
        chosenId = model.id;
        label();
        close();
        onPick(model.id);
      }
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const count = Math.min(visible.length, 200);
    if (!count) return;
    cursor = (cursor + (event.key === 'ArrowDown' ? 1 : count - 1)) % count;
    draw();
    scrollToCursor();
  });

  // Clicking anywhere else puts it away, which is what a dropdown does.
  document.addEventListener('pointerdown', (event) => {
    if (!panel.hidden && !wrap.contains(event.target)) close();
  });

  wrap._redraw = () => { label(); if (!panel.hidden) draw(); else drawStatus(); };
  wrap._setCurrent = (id) => { chosenId = id; label(); };
  label();
  return wrap;
}

function loadModels(provider, refresh) {
  get('/api/models?provider=' + encodeURIComponent(provider)
      + (refresh ? '&refresh=1' : '')).then((data) => {
    if (!data) return;
    modelIndex = {
      provider, models: data.models || [], source: data.source,
      age: data.age_seconds || 0, error: data.error || '',
    };
    window.modelIndex = modelIndex;
    document.querySelectorAll('.combo').forEach((combo) => {
      if (combo._redraw) combo._redraw();
    });
  });
}

/* -- the panel -------------------------------------------------------------- */

function drawAdmin(data) {
  state.admin = data;
  els.adminBody.textContent = '';

  /* -- what answers ------------------------------------------------------ */
  {
    const body = card('Model');

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
    field(body, 'Provider', providerPick);

    const combo = modelCombo(data.model.model, (id) => change('model', id));
    field(body, 'Model', combo);

    // The key. Somebody who set this up with the wrong one, or rotated it,
    // had to find a terminal.
    const keyRow = document.createElement('div');
    keyRow.className = 'key-row';
    const key = document.createElement('input');
    key.type = 'password';
    key.id = 'admin-key';
    key.className = 'mono';
    key.autocomplete = 'off';
    key.placeholder = data.model.has_key ? 'a key is set — paste a new one to replace it'
                                         : 'no key set';
    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'small';
    save.textContent = 'Save';
    save.onclick = () => {
      if (!key.value.trim()) { toast('Nothing to save', 'bad', 'key'); return; }
      post('/api/setting', { key: 'api_key', value: key.value })
        .then((reply) => {
          if (!reply.saved) { toast(reply.error || 'That did not take', 'bad', 'key'); return; }
          key.value = '';
          toast('Key saved', 'good', 'key');
          refreshAdmin();
        });
    };
    keyRow.append(key, save);
    field(body, 'API key', keyRow,
          data.model.has_key ? data.paths.config : 'This provider has no key yet',
          data.model.has_key ? 'path' : '');
  }

  /* -- where it works ---------------------------------------------------- */
  drawFolderCard();

  /* -- how far it goes on its own --------------------------------------- */
  {
    const body = card('How it runs');

    const modePick = document.createElement('select');
    modePick.id = 'pick-mode';
    ['act', 'plan', 'ask', 'chat'].forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name[0].toUpperCase() + name.slice(1);
      if (name === data.agent.mode) option.selected = true;
      modePick.appendChild(option);
    });
    const modeNote = field(body, 'Mode', modePick, MODE_NOTE[data.agent.mode] || '');
    modePick.onchange = () => {
      modePick.closest('.control').querySelector('.aside').textContent =
        MODE_NOTE[modePick.value] || '';
      change('mode', modePick.value);
    };

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
    body.appendChild(loop);

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
    body.appendChild(facts);
  }

  /* -- skills ------------------------------------------------------------ */
  drawLocalCard();
  drawSkillsCard();

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
      ? 'the working folder' : 'anywhere');
    if (data.safety.grants.length) {
      row(facts, 'Granted', data.safety.grants.join(', '));
    }

    const note = document.createElement('p');
    note.className = 'aside';
    note.style.marginTop = '10px';
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
    const stat = (value, label, hint) => {
      const box = document.createElement('div');
      box.className = 'stat';
      if (hint) box.title = hint;
      const big = document.createElement('b');
      big.textContent = value;
      const small = document.createElement('span');
      small.textContent = label;
      box.append(big, small);
      grid.appendChild(box);
    };
    stat(data.reflex.rules_active, 'rules here',
         'Rules in force in this folder. Click the Rules tab to see them.');
    stat(data.reflex.lessons, 'lessons');
    stat(data.reflex.skills, 'skills');
    stat(data.reflex.episodes, 'tasks');
    stat(data.reflex.signals, 'signals');
    stat(data.reflex.episodes ? Math.round(data.reflex.success_rate * 100) + '%' : '—',
         'succeeded', data.reflex.episodes ? '' : 'No finished tasks yet');
    body.appendChild(grid);

    if (data.reflex.rules_elsewhere) {
      const other = document.createElement('p');
      other.className = 'aside';
      other.style.marginTop = '10px';
      other.textContent = data.reflex.rules_elsewhere
        + ' more rules were learned in other folders. They do not apply here.';
      body.appendChild(other);
    }
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

    if (data.mcp.enabled && data.mcp.servers.length) {
      const heading = document.createElement('p');
      heading.className = 'aside';
      heading.style.margin = '12px 0 6px';
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

    /* From a phone, set up rather than only reported. */
    drawChannels();
  }

  /* -- where things are -------------------------------------------------- */
  {
    const body = card('This machine');
    const facts = document.createElement('dl');
    facts.className = 'kv';
    row(facts, 'Version', data.app.version);
    row(facts, 'Python', data.app.python);
    row(facts, 'System', data.app.platform);
    row(facts, 'Settings', data.paths.config);
    row(facts, 'Chats', data.paths.sessions);
    row(facts, 'Brain', data.paths.brain);
    facts.querySelectorAll('dd').forEach((dd, index) => {
      if (index >= 3) dd.className = 'path';
    });
    body.appendChild(facts);
  }

  els.reflexBit.hidden = !data.reflex.rules_active;
  els.reflex.textContent = data.reflex.rules_active;
  els.reflexBit.style.cursor = 'pointer';
  els.reflexBit.title = 'The rules in force in this folder — click to see them';
  els.reflexBit.onclick = () => { setRail(true); selectTab($('tab-rules')); };

  loadModels(data.model.provider, false);
}


/* Telegram, WhatsApp and Slack, set up from here rather than only from a
   terminal. Somebody running Comodor on a machine they reach over SSH should
   not have to learn a second vocabulary to connect a bot to it.

   The server refuses every one of these unless the request came from the
   machine Comodor is running on: a bot token hands remote control of it to
   whoever holds the token, and pairing adds somebody to the list of people who
   may drive it. Neither belongs to a page loaded from somewhere else. */
async function drawChannels() {
  const answer = await fetch('/api/channels').then((r) => r.json())
    .catch(() => null);
  if (!answer || !answer.channels) return;

  const body = card('From your phone');
  const note = document.createElement('p');
  note.className = 'aside';
  note.textContent = 'The same agent, reached from a chat app. '
    + 'It reads and plans only until you say otherwise.';
  body.appendChild(note);

  answer.channels.forEach((channel) => drawChannel(body, channel, answer));
}

function drawChannel(parent, channel, answer) {
  const box = document.createElement('div');
  box.className = 'control';
  box.style.display = 'block';
  box.style.marginTop = '14px';

  const head = document.createElement('p');
  head.style.margin = '0 0 4px';
  const name = document.createElement('strong');
  name.textContent = channel.label;
  const state = document.createElement('span');
  state.className = 'aside';
  state.style.marginLeft = '8px';
  // A leading space as well as the margin: the margin is what a reader sees,
  // and the space is what anything reading the text out of the page sees.
  state.textContent = ' ' + channelState(channel);
  head.append(name, state);
  box.appendChild(head);

  if (!channel.connected) {
    drawConnect(box, channel);
  } else {
    drawControls(box, channel, answer);
  }
  parent.appendChild(box);
}

function channelState(channel) {
  if (!channel.connected) return 'not connected';
  const bits = [];
  bits.push(channel.paired + (channel.paired === 1 ? ' account' : ' accounts')
            + ' paired');
  bits.push(channel.running ? 'running (up ' + channel.uptime + ')'
                            : 'not running');
  if (channel.at_login) bits.push('starts at login');
  bits.push(channel.writes ? 'may edit files' : 'reads only');
  return bits.join(' · ');
}

function drawConnect(parent, channel) {
  const inputs = {};
  channel.needs.forEach((need) => {
    const input = document.createElement('input');
    input.type = 'password';
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.placeholder = need.hint || '';
    inputs[need.key] = input;
    field(parent, need.label, input, need.hint);
  });

  const said = document.createElement('p');
  said.className = 'aside';

  const connect = document.createElement('button');
  connect.className = 'btn';
  connect.textContent = 'Connect';
  connect.onclick = async () => {
    const payload = { action: 'connect', channel: channel.name };
    Object.keys(inputs).forEach((key) => {
      payload[key] = inputs[key].value.trim();
    });
    connect.disabled = true;
    said.textContent = 'checking…';
    const reply = await post('/api/channels', payload);
    connect.disabled = false;
    if (reply && reply.ok) {
      redrawChannels();
    } else {
      said.textContent = (reply && reply.error) || 'that did not work';
    }
  };

  const row = document.createElement('div');
  row.className = 'row';
  row.append(connect, said);
  parent.appendChild(row);
}

function drawControls(parent, channel, answer) {
  const said = document.createElement('p');
  said.className = 'aside';

  const act = async (action, extra) => {
    said.textContent = 'working…';
    const reply = await post('/api/channels',
      Object.assign({ action, channel: channel.name }, extra || {}));
    if (reply && reply.ok) {
      said.textContent = reply.message || '';
      redrawChannels();
    } else {
      said.textContent = (reply && reply.error) || 'that did not work';
    }
  };

  const row = document.createElement('div');
  row.className = 'row';

  if (channel.pairable) {
    const pair = document.createElement('button');
    pair.className = 'btn';
    pair.textContent = channel.paired ? 'Pair another' : 'Pair an account';
    pair.onclick = () => act('pair');
    row.appendChild(pair);
  }

  const run = document.createElement('button');
  run.className = 'btn';
  run.textContent = channel.running ? 'Stop' : 'Start in the background';
  run.disabled = !channel.ready && !channel.running;
  run.onclick = () => act(channel.running ? 'stop' : 'start');
  row.appendChild(run);

  const login = document.createElement('button');
  login.className = 'btn';
  login.textContent = channel.at_login ? 'Do not start at login'
                                       : 'Start at login';
  login.onclick = () => act(channel.at_login ? 'uninstall' : 'install');
  row.appendChild(login);

  const writes = document.createElement('button');
  writes.className = 'btn';
  writes.textContent = channel.writes ? 'Make it read-only'
                                      : 'Let it edit files';
  writes.onclick = () => act('writes', { value: !channel.writes });
  row.appendChild(writes);

  if (channel.paired) {
    const forget = document.createElement('button');
    forget.className = 'btn';
    forget.textContent = 'Forget everybody';
    forget.onclick = () => act('forget', { who: 'all' });
    row.appendChild(forget);
  }

  parent.append(row, said);

  if (!channel.ready && channel.blocked) {
    const why = document.createElement('p');
    why.className = 'aside';
    why.textContent = channel.blocked;
    parent.appendChild(why);
  }

  const pairing = answer.pairing;
  if (pairing && pairing.channel === channel.name && pairing.code) {
    parent.appendChild(pairingBox(channel, pairing));
  }
}

function pairingBox(channel, pairing) {
  const box = document.createElement('div');
  box.className = 'control';
  box.style.display = 'block';
  box.style.marginTop = '8px';

  if (pairing.done) {
    const done = document.createElement('p');
    done.textContent = 'Paired.';
    box.appendChild(done);
    return box;
  }

  const what = document.createElement('p');
  what.style.margin = '0 0 4px';
  const where = {
    telegram: 'Message the bot on Telegram with this code:',
    discord: 'Send the bot a direct message on Discord with this code:',
    slack: 'Send Comodor a direct message in Slack with this code:',
  };
  what.textContent = where[channel.name] || where.slack;

  const code = document.createElement('strong');
  code.style.fontSize = '1.4em';
  code.style.letterSpacing = '0.12em';
  code.textContent = pairing.code;

  const clock = document.createElement('p');
  clock.className = 'aside';
  clock.textContent = pairing.seconds_left + 's left. '
    + 'The code works once.';

  box.append(what, code, clock);
  return box;
}

/* The panel is redrawn whole rather than patched: every one of these actions
   changes two or three of the things on it, and a half-updated panel is how
   somebody ends up believing a bot is running when it is not. */
function redrawChannels() {
  setTimeout(refreshAdmin, 150);
}

/* -- the folder the agent works in ----------------------------------------- */

function drawFolderCard() {
  const body = card('Working folder');
  const holder = document.createElement('div');
  holder.id = 'folder-body';
  body.appendChild(holder);
  get('/api/folder').then((data) => { if (data) drawFolder(holder, data); });
}

function drawFolder(holder, data) {
  holder.textContent = '';

  const now = document.createElement('p');
  now.className = 'path current-folder';
  now.textContent = data.current;
  holder.appendChild(now);

  const what = document.createElement('p');
  what.className = 'aside';
  what.textContent = data.confined
    ? 'The agent reads and writes here and nowhere else.'
    : 'The agent starts here. It is not confined to it — see Permissions.';
  holder.appendChild(what);

  const line = document.createElement('form');
  line.className = 'key-row';
  const typed = document.createElement('input');
  typed.type = 'text';
  typed.id = 'pick-folder';
  typed.className = 'mono';
  typed.placeholder = 'another folder, by path';
  typed.setAttribute('aria-label', 'Change the working folder');
  const go = document.createElement('button');
  go.type = 'submit';
  go.className = 'small';
  go.textContent = 'Move';
  line.append(typed, go);
  line.onsubmit = (event) => {
    event.preventDefault();
    if (typed.value.trim()) moveTo(typed.value.trim(), data);
  };
  holder.appendChild(line);

  if (data.siblings.length) {
    const near = document.createElement('div');
    near.className = 'folder-list';
    data.siblings.slice(0, 40).forEach((child) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'folder-row';
      if (child.path === data.current) row.setAttribute('aria-current', 'true');
      const name = document.createElement('b');
      name.textContent = child.name;
      row.appendChild(name);
      if (child.marked) {
        const tag = document.createElement('em');
        tag.textContent = 'project';
        row.appendChild(tag);
      }
      row.onclick = () => moveTo(child.path, data);
      near.appendChild(row);
    });
    holder.appendChild(near);
  }
}

function moveTo(where, data) {
  // Asked, because a different folder is a different project: its own rules,
  // its own checkpoints, and a conversation that starts empty. Finding that
  // out afterwards is finding out you have lost your place.
  const warn = data.messages
    ? `Move to\n\n    ${where}\n\nThat is a different project. This `
      + `conversation (${data.messages} messages) is saved and a new one starts `
      + `there, with that folder's own learned rules.`
    : `Work in\n\n    ${where}\n\nThe agent will read and write there.`;
  if (!confirm(warn)) return;

  post('/api/folder', { path: where }).then((reply) => {
    if (!reply.ok) { toast(reply.error || 'Could not move there', 'bad', 'folder'); return; }
    takeState(reply.state);
    state.cursor = reply.state.cursor;
    els.stream.textContent = '';
    live = null;
    running.clear();
    showBlank();
    refreshChats();
    refreshRules();
    refreshAdmin();
    toast('Working in ' + (reply.folder.name || where), 'good', 'folder');
  });
}

/* -- models on this machine -------------------------------------------------- */

function drawLocalCard() {
  const body = card('Local LLM');

  const note = document.createElement('p');
  note.className = 'lm-note';
  body.appendChild(note);

  const missing = document.createElement('p');
  missing.className = 'lm-missing';
  missing.hidden = true;
  missing.textContent =
    'No llama.cpp server was found, so a downloaded model cannot run yet. '
    + 'Install one — brew install llama.cpp, winget install llama.cpp, or a '
    + 'build from github.com/ggml-org/llama.cpp. Ollama and LM Studio work too.';
  body.appendChild(missing);

  const holder = document.createElement('div');
  holder.id = 'local-models';
  body.appendChild(holder);

  localState.holder = holder;
  localState.note = note;
  localState.runtime = missing;
  loadLocal();
}

/* -- skills ----------------------------------------------------------------- */

function drawSkillsCard() {
  const body = card('Skills');
  const holder = document.createElement('div');
  holder.id = 'skills-manage';
  body.appendChild(holder);
  get('/api/skills').then((data) => { if (data) drawSkills(holder, data); });
}

function drawSkills(holder, data) {
  holder.textContent = '';

  if (data.error) {
    const note = document.createElement('p');
    note.className = 'aside warn';
    note.textContent = 'The library could not be reached (' + data.error
      + '), so only what is installed is listed.';
    holder.appendChild(note);
  }

  if (!data.skills.length) {
    const none = document.createElement('p');
    none.className = 'empty-note';
    none.style.textAlign = 'start';
    none.textContent = 'Nothing installed and nothing to offer right now.';
    holder.appendChild(none);
    return;
  }

  data.skills.forEach((skill) => {
    const box = document.createElement('div');
    box.className = 'skill';
    box.dataset.installed = String(skill.installed);
    box.dataset.enabled = String(skill.enabled);

    const head = document.createElement('div');
    head.className = 'skill-head';
    const name = document.createElement('b');
    name.textContent = skill.name;
    head.appendChild(name);
    if (skill.scope === 'project') {
      const tag = document.createElement('em');
      tag.textContent = 'this project';
      head.appendChild(tag);
    }
    box.appendChild(head);

    if (skill.description) {
      const what = document.createElement('p');
      what.className = 'aside';
      what.textContent = skill.description;
      box.appendChild(what);
    }

    const doings = document.createElement('div');
    doings.className = 'skill-doings';

    if (skill.installed) {
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'small';
      toggle.textContent = skill.enabled ? 'Switch off' : 'Switch on';
      toggle.onclick = () => skillAction(skill.enabled ? 'disable' : 'enable',
                                         skill.name, holder);
      doings.appendChild(toggle);

      if (skill.managed) {
        const drop = document.createElement('button');
        drop.type = 'button';
        drop.className = 'small danger';
        drop.textContent = 'Remove';
        drop.onclick = () => {
          if (!confirm(`Remove the "${skill.name}" skill from disk?`)) return;
          skillAction('remove', skill.name, holder);
        };
        doings.appendChild(drop);
      } else {
        const mine = document.createElement('span');
        mine.className = 'aside';
        mine.textContent = 'yours — Comodor will not delete it';
        doings.appendChild(mine);
      }
    } else {
      const add = document.createElement('button');
      add.type = 'button';
      add.className = 'small primary';
      add.textContent = 'Install';
      add.onclick = () => skillAction('install', skill.name, holder);
      doings.appendChild(add);
    }

    box.appendChild(doings);
    holder.appendChild(box);
  });
}

function skillAction(action, name, holder) {
  post('/api/skills', { action, name }).then((reply) => {
    if (!reply.ok) { toast(reply.error || 'That did not take', 'bad', 'skill'); return; }
    toast({ install: 'Installed ' + name, remove: 'Removed ' + name,
            enable: name + ' is on', disable: name + ' is off' }[action] || 'Done',
          'good', 'skill');
    get('/api/skills').then((data) => { if (data) drawSkills(holder, data); });
  });
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
const tabs = [$('tab-chat'), $('tab-rules'), $('tab-admin')];
const ON_OPEN = { 'tab-rules': () => { refreshRules(); },
                  'tab-admin': () => refreshAdmin() };

function selectTab(which) {
  tabs.forEach((tab) => {
    const on = tab === which;
    tab.setAttribute('aria-selected', String(on));
    tab.tabIndex = on ? 0 : -1;
    $(tab.getAttribute('aria-controls')).dataset.open = String(on);
  });
  const refresh = ON_OPEN[which.id];
  if (refresh) refresh();
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
  selectTab($('tab-admin'));
};

/* ------------------------------------------------------------- rail width
 *
 * 292 pixels is a reasonable default and a bad only-option. Chat titles are as
 * long as the first thing somebody typed and the Rules panel holds sentences,
 * so the person reading them should be able to make room — and the person on a
 * laptop should be able to take it back.
 */

const RAIL_MIN = 220;
const RAIL_MAX = 520;
const WIDTH_KEY = 'comodor-rail-width';

function setRailWidth(px, remember) {
  const width = Math.round(Math.max(RAIL_MIN, Math.min(RAIL_MAX, px)));
  els.shell.style.setProperty('--rail', width + 'px');
  $('rail-grip').setAttribute('aria-valuenow', String(width));
  if (remember) {
    try { localStorage.setItem(WIDTH_KEY, String(width)); } catch { /* ignore */ }
  }
  // A title that fitted at 292 may not fit at 240. The fade is measured, not
  // guessed, so it has to be measured again.
  remeasureTitles();
  return width;
}

function remeasureTitles() {
  requestAnimationFrame(() => {
    document.querySelectorAll('.chat-row .title').forEach((title) => {
      title.dataset.clipped = String(title.scrollWidth > title.clientWidth + 1);
    });
  });
}

(function restoreRailWidth() {
  if (narrow()) return;
  let stored = null;
  try { stored = localStorage.getItem(WIDTH_KEY); } catch { /* private window */ }
  if (stored) setRailWidth(parseInt(stored, 10) || RAIL_MIN, false);
})();

(function makeRailDraggable() {
  const grip = $('rail-grip');
  let dragging = false;

  const move = (event) => {
    if (!dragging) return;
    // From the shell's own left edge, not the window's: in a right-to-left
    // document the rail is on the other side and clientX counts the other way.
    const box = els.shell.getBoundingClientRect();
    const rtl = getComputedStyle(document.documentElement).direction === 'rtl';
    setRailWidth(rtl ? box.right - event.clientX : event.clientX - box.left, false);
  };

  const stop = () => {
    if (!dragging) return;
    dragging = false;
    grip.dataset.dragging = 'false';
    document.body.dataset.dragging = 'false';
    const width = parseInt(grip.getAttribute('aria-valuenow'), 10);
    setRailWidth(width, true);
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', stop);
  };

  grip.addEventListener('pointerdown', (event) => {
    if (narrow()) return;
    event.preventDefault();
    dragging = true;
    grip.dataset.dragging = 'true';
    document.body.dataset.dragging = 'true';
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
  });

  // A handle only a mouse can reach is a handle half the people cannot use.
  grip.addEventListener('keydown', (event) => {
    const step = event.shiftKey ? 48 : 12;
    const now = parseInt(grip.getAttribute('aria-valuenow'), 10) || RAIL_MIN;
    if (event.key === 'ArrowLeft') setRailWidth(now - step, true);
    else if (event.key === 'ArrowRight') setRailWidth(now + step, true);
    else if (event.key === 'Home') setRailWidth(RAIL_MIN, true);
    else if (event.key === 'End') setRailWidth(RAIL_MAX, true);
    else return;
    event.preventDefault();
  });

  // Double-click puts it back, which is the escape hatch for having dragged
  // it somewhere silly.
  grip.addEventListener('dblclick', () => setRailWidth(292, true));
})();

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
  selectTab($('tab-admin'));
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
    selectTab($('tab-chat'));
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
  if (data.needs_setup === false && els.prompt.disabled) {
    els.prompt.disabled = false;
    els.prompt.placeholder = 'Ask for something…';
  }
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

  if (data && data.needs_setup) {
    // Nothing to say to a model that has not been chosen. The questions take
    // the place of the conversation rather than sitting over it.
    askForSetup();
    refreshChats();
    poll();
    return;
  }

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
