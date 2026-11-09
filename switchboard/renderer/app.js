/* global sb */
'use strict';

const SERVICES = {
  discord: { name: 'Discord', letter: 'D' },
  mattermost: { name: 'Mattermost', letter: 'M' },
  slack: { name: 'Slack', letter: 'S' },
  teams: { name: 'Teams', letter: 'T' },
  web: { name: 'Web', letter: 'W' },
};
const MOBILE = sb.platform === 'android'; // phone build: one pane at a time, no desktop notifications
const LIST_LIMIT = 400;
const PAGE = 50;

const state = {
  settings: null,
  statuses: {},
  convs: new Map(), // key -> conversation
  messages: new Map(), // key -> [message]
  exhausted: new Set(), // keys whose full history is loaded
  openKey: null,
  openApp: null,
  appBadges: {},
  filter: 'all',
  query: '',
  loadingOlder: false,
  view: { mode: 'all', keys: new Set(), groups: [], assign: new Map(), nicknames: new Map(), pins: [], otherCollapsed: false, compact: false, flat: false },
  editing: false,
  editTab: 'show', // Edit chooses which chats to 'show' or to 'pin'
  dragKey: null, // chat being dragged onto a group
  renaming: null, // group id whose name is being edited
  renamingConv: null, // chat key whose nickname is being edited
  renderPending: false,
  searchKey: null, // match that Enter opens while searching
  floatKey: null, // open chat that was unread when opened; stays on top until you leave it
};

// ---------- helpers ----------

const $ = sel => document.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

const cleanError = e => String(e?.message || e).replace(/^Error invoking remote method '[^']+': (Error: )?/, '');

let toastTimer;
function toast(text) {
  const el = $('#toast');
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 5000);
}

function hashColor(s) {
  let n = 0;
  for (const ch of s) n = (n * 31 + ch.codePointAt(0)) | 0;
  return `hsl(${Math.abs(n) % 360} 45% 48%)`;
}

function initials(name) {
  const words = name.split(/\s+/).map(w => w.replace(/[^\p{L}\p{N}]/gu, '')).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || '?').slice(0, 2)).toUpperCase();
}

function avatarEl(name, url, cls = '') {
  const fallback = () => h('div', { class: `avatar ${cls}`, style: `background:${hashColor(name)}` }, initials(name));
  if (!url) return fallback();
  const img = h('img', { class: `avatar ${cls}`, src: url, alt: '' });
  img.addEventListener('error', () => img.replaceWith(fallback()), { once: true });
  return img;
}

const dayKey = ts => new Date(ts).toDateString();
const formatTime = ts => new Date(ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

function formatDay(ts) {
  const d = new Date(ts);
  const today = new Date();
  const yesterday = new Date(Date.now() - 864e5);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric', year: d.getFullYear() === today.getFullYear() ? undefined : 'numeric' });
}

function formatListTime(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  const age = Date.now() - ts;
  if (d.toDateString() === new Date().toDateString()) return formatTime(ts);
  if (age < 6 * 864e5) return d.toLocaleDateString([], { weekday: 'short' });
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function linkify(text) {
  const out = [];
  const re = /https?:\/\/[^\s<>"')\]]+/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const url = m[0];
    out.push(h('a', { href: '#', onclick: e => { e.preventDefault(); sb.openExternal(url); } }, url));
    last = m.index + url.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// ---------- sidebar ----------

// mode 'all': every chat shows except the hidden keys; new chats appear.
// mode 'selected': only the chosen keys show; new chats stay hidden.
function isVisible(c) {
  return state.view.mode === 'all' ? !state.view.keys.has(c.key) : state.view.keys.has(c.key);
}

// What the list shows: chosen chats, plus hidden ones with something unread
// (or currently open), so new messages always surface. Once read and left,
// a hidden chat drops out again unless it is kept or put in a group.
function isListed(c) {
  return isVisible(c) || c.unread || c.mentions > 0 || c.key === state.openKey;
}

// Nicknames are local only; the original title is kept for search and display.
function displayTitle(c) {
  return state.view.nicknames.get(c.key) || c.title;
}

function setNickname(key, name) {
  const conv = state.convs.get(key);
  const trimmed = (name || '').trim().slice(0, 80);
  if (!trimmed || trimmed === conv?.title) state.view.nicknames.delete(key);
  else state.view.nicknames.set(key, trimmed);
  saveView();
  if (conv && key === state.openKey) renderHeader(conv);
}

function inlineInput(cls, value, done) {
  const input = h('input', { class: cls, value, maxlength: '80' });
  let finished = false;
  const finish = save => {
    if (finished) return;
    finished = true;
    done(save ? input.value : null);
  };
  input.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Enter') finish(true);
    else if (e.key === 'Escape') finish(false);
  });
  input.addEventListener('blur', () => finish(true));
  input.addEventListener('click', e => e.stopPropagation());
  setTimeout(() => {
    input.focus();
    input.select();
  });
  return input;
}

function startRenameConv(key) {
  state.renamingConv = key;
  renderSidebar();
}

function finishRenameConv(key, value) {
  state.renamingConv = null;
  if (value != null) setNickname(key, value);
  renderSidebar();
}

function saveView() {
  const v = state.view;
  sb.setView({
    mode: v.mode,
    keys: [...v.keys],
    groups: v.groups,
    assign: Object.fromEntries(v.assign),
    nicknames: Object.fromEntries(v.nicknames),
    pins: v.pins,
    otherCollapsed: v.otherCollapsed,
    compact: v.compact,
    flat: v.flat,
  }).catch(e => toast(cleanError(e)));
}

function setVisible(keys, visible) {
  for (const key of keys) {
    if (visible === (state.view.mode === 'all')) state.view.keys.delete(key);
    else state.view.keys.add(key);
  }
  saveView();
  scheduleRender();
}

// Changing the mode only changes what happens to new chats; current choices stay.
function setNewChatsShown(shown) {
  const mode = shown ? 'all' : 'selected';
  if (mode === state.view.mode) return;
  const all = [...state.convs.values()];
  const visible = new Set(all.filter(isVisible).map(c => c.key));
  state.view.mode = mode;
  state.view.keys = new Set(all.filter(c => (mode === 'all') !== visible.has(c.key)).map(c => c.key));
  saveView();
  scheduleRender();
}

function setEditing(on) {
  state.editing = on;
  renderSidebar();
}

// Latest first: ignore groups and show one list ordered by newest message.
function setFlat(on, announce = false) {
  state.view.flat = on;
  if (announce) toast(on ? 'Latest first: on' : 'Latest first: off (grouped)');
  saveView();
  renderSidebar();
  if (!$('#settings').hidden) renderSettings();
}

function setCompact(on) {
  state.view.compact = on;
  saveView();
  renderSidebar();
  if (!$('#settings').hidden) renderSettings();
}

// ----- groups -----

const OTHER = { id: '', name: 'Other' };

function groupOf(key) {
  const gid = state.view.assign.get(key);
  return gid && state.view.groups.some(g => g.id === gid) ? gid : '';
}

// Putting a chat in a group also keeps it in the list.
function assignGroup(keys, gid) {
  for (const key of keys) {
    if (isPinned(key) && groupOf(key) !== gid) {
      state.view.pins = [...state.view.pins.filter(k => k !== key), key];
    }
    if (gid) {
      state.view.assign.set(key, gid);
      if (state.view.mode === 'all') state.view.keys.delete(key);
      else state.view.keys.add(key);
    } else {
      state.view.assign.delete(key);
    }
  }
  saveView();
  scheduleRender();
}

function createGroup(keys = []) {
  const g = { id: `g${Date.now().toString(36)}`, name: 'New group', collapsed: false };
  state.view.groups.push(g);
  state.renaming = g.id;
  assignGroup(keys, g.id); // saves; render now since scheduled renders wait during a rename
  renderSidebar();
}

function deleteGroup(g) {
  state.view.groups = state.view.groups.filter(x => x !== g);
  for (const [key, gid] of state.view.assign) if (gid === g.id) state.view.assign.delete(key);
  saveView();
  scheduleRender();
}

function moveGroup(g, delta) {
  const list = state.view.groups;
  const i = list.indexOf(g);
  const j = i + delta;
  if (j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
  saveView();
  scheduleRender();
}

function toggleGroup(g) {
  if (g === OTHER) state.view.otherCollapsed = !state.view.otherCollapsed;
  else g.collapsed = !g.collapsed;
  saveView();
  scheduleRender();
}

function finishRename(g, name) {
  if (state.renaming !== g.id) return;
  state.renaming = null;
  if (name.trim()) g.name = name.trim().slice(0, 60);
  saveView();
  renderSidebar();
}
// ----- pins -----

const isPinned = key => state.view.pins.includes(key);

// A group is its pinned chats (in the order you set) and then the rest (newest
// first); in each part, chats with unread messages move to the top.
function splitGroup(items) {
  const rank = new Map(state.view.pins.map((k, i) => [k, i]));
  const floats = c => !c.muted && (unreadOf(c) > 0 || (c.key === state.floatKey && c.key === state.openKey));
  const pinned = items.filter(c => rank.has(c.key)).sort((a, b) => floats(b) - floats(a) || rank.get(a.key) - rank.get(b.key));
  const rest = items.filter(c => !rank.has(c.key)).sort((a, b) => floats(b) - floats(a));
  return { pinned, rest };
}

function groupRows(items) {
  if (state.editing || state.view.flat) return items.slice(0, LIST_LIMIT).map(convRow); // rows stay put while you tick them
  const { pinned, rest } = splitGroup(items);
  return [
    ...pinned.map(convRow),
    ...(pinned.length && rest.length ? [h('div', { class: 'pin-divider' })] : []),
    ...rest.slice(0, LIST_LIMIT).map(convRow),
  ];
}

// Pinned chats in the same group as key, in pin order
function groupPins(key) {
  const gid = groupOf(key);
  return state.view.pins.filter(k => state.convs.has(k) && groupOf(k) === gid);
}

function setPinned(keys, on) {
  for (const key of keys) {
    const was = isPinned(key);
    if (was && !on) state.view.pins = state.view.pins.filter(k => k !== key);
    if (!was && on) state.view.pins.push(key);
  }
  if (on) setVisible(keys, true); // saves and renders
  else {
    saveView();
    scheduleRender();
  }
}

function movePin(key, delta) {
  const pins = groupPins(key);
  const other = pins[pins.indexOf(key) + delta];
  if (!other) return;
  const all = state.view.pins;
  const a = all.indexOf(key);
  const b = all.indexOf(other);
  [all[a], all[b]] = [all[b], all[a]];
  saveView();
  scheduleRender();
}

// Dropping a chat on a pinned one pins it in that spot.
function pinAt(key, targetKey) {
  const pins = state.view.pins;
  const from = pins.indexOf(key);
  if (from !== -1) pins.splice(from, 1);
  const to = pins.indexOf(targetKey);
  pins.splice(from !== -1 && from <= to ? to + 1 : to, 0, key);
  saveView();
  scheduleRender();
}

async function convMenu(c) {
  const current = groupOf(c.key);
  const pins = groupPins(c.key);
  const pinIndex = pins.indexOf(c.key);
  const choice = await sb.popupMenu([
    {
      label: 'Move to group',
      submenu: [
        ...state.view.groups.map(g => ({ id: `group:${g.id}`, label: g.name, checked: g.id === current })),
        ...(state.view.groups.length ? [{ type: 'separator' }] : []),
        { id: 'group:new', label: 'New group…' },
        ...(current ? [{ id: 'group:', label: 'Remove from group' }] : []),
      ],
    },
    ...(pinIndex === -1 ? [{ id: 'pin', label: state.view.groups.length ? 'Pin to top of group' : 'Pin to top' }] : [
      { id: 'unpin', label: 'Unpin' },
      { id: 'pin-up', label: 'Move pin up', enabled: pinIndex > 0 },
      { id: 'pin-down', label: 'Move pin down', enabled: pinIndex < pins.length - 1 },
    ]),
    { type: 'separator' },
    { id: 'rename', label: 'Rename (only you see this)…' },
    ...(state.view.nicknames.has(c.key) ? [{ id: 'reset', label: `Reset name to "${c.title}"` }] : []),
    { type: 'separator' },
    ...(c.unread || c.mentions ? [{ id: 'read', label: 'Mark as read' }] : []),
    isVisible(c) ? { id: 'hide', label: 'Hide from list' } : { id: 'keep', label: 'Keep in list' },
  ]);
  if (!choice) return;
  if (choice === 'group:new') createGroup([c.key]);
  else if (choice.startsWith('group:')) assignGroup([c.key], choice.slice(6));
  else if (choice === 'pin' || choice === 'unpin') setPinned([c.key], choice === 'pin');
  else if (choice === 'pin-up') movePin(c.key, -1);
  else if (choice === 'pin-down') movePin(c.key, 1);
  else if (choice === 'hide') setVisible([c.key], false);
  else if (choice === 'keep') setVisible([c.key], true);
  else if (choice === 'rename') startRenameConv(c.key);
  else if (choice === 'reset') {
    setNickname(c.key, '');
    scheduleRender();
  }
  else if (choice === 'read') {
    c.unread = false;
    c.mentions = 0;
    c.unreadCount = 0;
    sb.markRead(c.key).catch(() => {});
    scheduleRender();
  }
}

async function groupMenu(g) {
  const i = state.view.groups.indexOf(g);
  const choice = await sb.popupMenu([
    { id: 'rename', label: 'Rename' },
    { id: 'up', label: 'Move up', enabled: i > 0 },
    { id: 'down', label: 'Move down', enabled: i < state.view.groups.length - 1 },
    { type: 'separator' },
    { id: 'delete', label: 'Delete group (chats move to Other)' },
  ]);
  if (choice === 'rename') {
    state.renaming = g.id;
    renderSidebar();
  } else if (choice === 'up') moveGroup(g, -1);
  else if (choice === 'down') moveGroup(g, 1);
  else if (choice === 'delete') deleteGroup(g);
}

function dropTarget(el, gid, targetKey = null) {
  el.addEventListener('dragover', e => {
    if (!state.dragKey) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    el.classList.add('drop');
  });
  el.addEventListener('dragleave', () => el.classList.remove('drop'));
  el.addEventListener('drop', e => {
    e.preventDefault();
    el.classList.remove('drop');
    const key = state.dragKey;
    state.dragKey = null;
    if (key && groupOf(key) !== gid) assignGroup([key], gid);
    if (key && targetKey && key !== targetKey && isPinned(targetKey)) pinAt(key, targetKey);
  });
}

function renameInput(g) {
  const input = h('input', { class: 'group-rename', value: g.name, maxlength: '60' });
  input.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Enter') input.blur();
    else if (e.key === 'Escape') {
      input.value = g.name;
      input.blur();
    }
  });
  input.addEventListener('blur', () => finishRename(g, input.value));
  input.addEventListener('click', e => e.stopPropagation());
  setTimeout(() => {
    input.focus();
    input.select();
  });
  return input;
}

function groupHeader(g, items) {
  const isOther = g === OTHER;
  const collapsed = isOther ? state.view.otherCollapsed : g.collapsed;
  const unread = items.reduce((n, c) => n + (c.muted ? 0 : unreadOf(c)), 0);
  const el = h('div', {
    class: `group-head${collapsed ? ' collapsed' : ''}`,
    onclick: () => toggleGroup(g),
    oncontextmenu: e => {
      e.preventDefault();
      if (!isOther) groupMenu(g);
    },
  },
  h('span', { class: 'chev' }, '▾'),
  state.renaming === g.id && !isOther ? renameInput(g) : h('span', { class: 'group-name' }, g.name),
  unread ? h('span', { class: 'pill' }, countLabel(unread)) : state.editing ? h('span', { class: 'group-count' }, items.length) : null,
  isOther ? h('span', { class: 'group-more' }) : h('button', { class: 'group-more', title: 'Group options', onclick: e => { e.stopPropagation(); groupMenu(g); } }, '⋯'));
  dropTarget(el, g.id);
  return el;
}

// ----- list -----

let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    updateBadge();
    // Re-rendering mid-drag or mid-rename would destroy what the user is holding.
    if (state.dragKey || state.renaming || state.renamingConv) {
      state.renderPending = true;
      return;
    }
    state.renderPending = false;
    renderSidebar();
  });
}

function filteredConvs() {
  const q = state.query.trim().toLowerCase();
  return [...state.convs.values()]
    .filter(c => {
      if (!state.editing && !isListed(c)) return false;
      if (state.filter === 'unread' && !(c.unread || c.mentions)) return false;
      if (SERVICES[state.filter] && c.service !== state.filter) return false;
      if (q && !`${displayTitle(c)} ${c.title} ${c.subtitle}`.toLowerCase().includes(q)) return false;
      return true;
    })
    .sort((a, b) => (b.lastActivity || 0) - (a.lastActivity || 0));
}

function renderFilters() {
  const present = new Set([...state.convs.values()].map(c => c.service));
  const chips = [['all', 'All'], ['unread', 'Unread']];
  for (const s of ['discord', 'mattermost', 'slack']) if (present.has(s)) chips.push([s, SERVICES[s].name]);
  $('#filters').replaceChildren(
    ...chips.map(([id, label]) =>
      h('button', { class: `chip${state.filter === id ? ' on' : ''}`, onclick: () => { state.filter = id; renderSidebar(); } }, label)),
  );
}

function renderEditBar() {
  const bar = $('#edit-bar');
  bar.hidden = !state.editing;
  if (!state.editing) return;
  const list = filteredConvs();
  const pinTab = state.editTab === 'pin';
  const tabs = h('div', { class: 'edit-tabs' },
    ...[['show', 'Show'], ['pin', 'Pin']].map(([id, label]) =>
      h('button', { class: `chip${state.editTab === id ? ' on' : ''}`, onclick: () => { state.editTab = id; renderSidebar(); } }, label)));
  const top = h('div', { class: 'edit-top' },
    h('span', { class: 'edit-title' }, pinTab ? 'Choose chats to pin' : 'Choose chats to show'),
    h('button', { class: 'btn primary small', onclick: () => setEditing(false) }, 'Done'));
  if (pinTab) {
    const pinned = list.filter(c => isPinned(c.key));
    bar.replaceChildren(top, tabs,
      h('div', { class: 'edit-actions' },
        h('span', { class: 'edit-count' }, `${pinned.length} pinned`),
        pinned.length ? h('button', { class: 'link-btn', onclick: () => setPinned(pinned.map(c => c.key), false) }, 'Unpin all') : null),
      h('div', { class: 'edit-new' }, 'Pinned chats stay at the top of their group.'));
    return;
  }
  const shown = list.filter(isVisible).length;
  const newChats = h('input', { type: 'checkbox', checked: state.view.mode === 'all', onchange: e => setNewChatsShown(e.target.checked) });
  bar.replaceChildren(top, tabs,
    h('div', { class: 'edit-actions' },
      h('span', { class: 'edit-count' }, `${shown} of ${list.length} shown`),
      h('button', { class: 'link-btn', onclick: () => setVisible(list.map(c => c.key), true) }, 'Show all'),
      h('button', { class: 'link-btn', onclick: () => setVisible(list.map(c => c.key), false) }, 'Hide all')),
    h('label', { class: 'edit-new' }, newChats, 'Show new chats automatically'),
  );
}

function convRow(c) {
  const editing = state.editing;
  const visible = isVisible(c);
  const pinTab = editing && state.editTab === 'pin';
  const checked = pinTab ? isPinned(c.key) : visible;
  const count = Math.max(c.unreadCount || 0, c.mentions || 0);
  const badge = count ? h('span', { class: 'pill', title: c.mentions ? `${count} unread, ${c.mentions} mentioning you` : `${count} unread` }, countLabel(count))
    : c.unread ? h('span', { class: 'dot' }) : null;
  const name = displayTitle(c);
  const renaming = state.renamingConv === c.key;
  const title = () => (renaming
    ? inlineInput('conv-rename', name, v => finishRenameConv(c.key, v))
    : h('span', { class: 'conv-title' }, name));
  // An <input> can't live inside a <button>, so a row being renamed is a div.
  const el = h(renaming ? 'div' : 'button', {
    class: `conv${!editing && c.key === state.openKey ? ' active' : ''}${c.unread || c.mentions ? ' unread' : ''}${c.muted ? ' muted' : ''}${editing && !pinTab && !visible ? ' off' : ''}${!editing && !visible ? ' peek' : ''}`,
    'data-kind': c.kind,
    'data-key': c.key,
    title: !editing && !visible
      ? 'Hidden chat, shown because of a new message. Right-click → Keep in list to keep it.'
      : state.view.compact || name !== c.title ? `${name} · ${name !== c.title ? `${c.title} · ` : ''}${c.subtitle}` : null,
    draggable: editing || renaming ? null : 'true',
    onclick: () => (renaming ? null : pinTab ? setPinned([c.key], !checked) : editing ? setVisible([c.key], !visible) : openConversation(c.key)),
    oncontextmenu: e => {
      e.preventDefault();
      if (!editing) convMenu(c);
    },
    ondragstart: e => {
      state.dragKey = c.key;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', c.title);
    },
    ondragend: () => {
      state.dragKey = null;
      if (state.renderPending) scheduleRender();
    },
  },
  editing ? h('span', { class: `check${checked ? ' on' : ''}`, 'aria-hidden': 'true' }, checked ? '✓' : '') : null,
  h('div', { class: 'conv-avatar' },
    avatarEl(name, c.avatar),
    h('span', { class: `svc-badge svc-${c.service}` }, SERVICES[c.service]?.letter || '?')),
  state.view.compact
    ? h('div', { class: 'conv-main' },
      title(),
      c.kind === 'channel' ? h('span', { class: 'conv-inline-sub' }, c.subtitle) : null,
      badge)
    : h('div', { class: 'conv-main' },
      h('div', { class: 'conv-top' },
        title(),
        h('span', { class: 'conv-time' }, formatListTime(c.lastActivity))),
      h('div', { class: 'conv-bottom' },
        h('span', { class: 'conv-sub' }, c.subtitle),
        badge)));
  dropTarget(el, groupOf(c.key), c.key);
  return el;
}

function appRow(app) {
  const count = state.appBadges[app.id] || 0;
  const badge = count ? h('span', { class: 'pill' }, count) : null;
  return h('button', {
    class: `conv${state.openApp === app.id ? ' active' : ''}${count ? ' unread' : ''}`,
    'data-key': `app:${app.id}`,
    onclick: () => openApp(app.id),
  },
  h('div', { class: 'conv-avatar' },
    avatarEl(app.name, null),
    h('span', { class: `svc-badge svc-${app.service}` }, SERVICES[app.service]?.letter || 'W')),
  state.view.compact
    ? h('div', { class: 'conv-main' }, h('span', { class: 'conv-title' }, app.name), badge)
    : h('div', { class: 'conv-main' },
      h('div', { class: 'conv-top' }, h('span', { class: 'conv-title' }, app.name)),
      h('div', { class: 'conv-bottom' }, h('span', { class: 'conv-sub' }, 'Web app'), badge)));
}

function renderSidebar() {
  document.body.classList.toggle('compact', state.view.compact);
  $('#compact-btn').classList.toggle('on', state.view.compact);
  $('#flat-btn').classList.toggle('on', state.view.flat);
  $('#flat-btn').hidden = !state.view.groups.length;
  renderFilters();
  renderEditBar();
  $('#edit-btn').hidden = state.editing;
  $('#apps').replaceChildren(...(state.editing ? [] : (state.settings?.webApps || []).map(appRow)));

  const list = filteredConvs();
  const box = $('#convs');
  const scroll = box.scrollTop;
  const rows = [];
  const expandAll = state.editing || !!state.query.trim() || state.filter !== 'all';

  if (state.view.groups.length && !state.view.flat) {
    const buckets = new Map([...state.view.groups.map(g => [g.id, []]), ['', []]]);
    for (const c of list) buckets.get(groupOf(c.key)).push(c);
    for (const g of [...state.view.groups, OTHER]) {
      const items = buckets.get(g.id);
      if (!items.length && (expandAll || g === OTHER)) continue;
      const collapsed = g === OTHER ? state.view.otherCollapsed : g.collapsed;
      rows.push(groupHeader(g, items));
      if (collapsed && !expandAll) continue;
      rows.push(...groupRows(items));
      if (!items.length) rows.push(h('div', { class: 'group-empty' }, 'Drag a chat here, or right-click one'));
    }
  } else {
    rows.push(...groupRows(list));
    if (list.length > LIST_LIMIT) rows.push(h('div', { class: 'list-note' }, `${list.length - LIST_LIMIT} more; search to find them`));
  }

  if (!list.length && (!state.view.groups.length || state.view.flat)) {
    const connected = Object.values(state.statuses).some(s => s.state !== 'off');
    const hiddenAll = !state.editing && state.convs.size > 0;
    rows.push(h('div', { class: 'list-note' },
      state.query || state.filter !== 'all' ? 'Nothing matches'
        : hiddenAll ? 'No chats chosen yet. Click Edit to pick some.'
          : connected ? 'Loading conversations…' : 'Connect an account in Settings'));
  }
  const hidden = state.editing ? 0 : [...state.convs.values()].filter(c => !isListed(c)).length;
  if (hidden) rows.push(h('button', { class: 'list-note link-btn', onclick: () => setEditing(true) }, `${hidden} hidden · Edit`));
  if (!state.editing && state.convs.size) {
    rows.push(h('button', { class: 'list-note link-btn', onclick: () => createGroup() }, '+ New group'));
  }
  box.replaceChildren(...rows);
  box.scrollTop = scroll;
  markSearchPick();
}

function renderStatus() {
  const items = Object.values(state.statuses)
    .filter(s => s.state !== 'off')
    .map(s => h('span', {
      class: `status ${s.state}`,
      title: s.error || (s.user ? `Signed in as ${s.user}` : s.state),
      onclick: openSettings,
    }, h('i'), s.label || s.provider));
  $('#statuses').replaceChildren(...items);
}

// Unread messages in a chat; 1 when a service says "unread" without a count.
function unreadOf(c) {
  return Math.max(c.unreadCount || 0, c.mentions || 0, c.unread ? 1 : 0);
}

function countLabel(n) {
  return n > 99 ? '99+' : String(n);
}

// Dock badge: unread messages in chats you chose to show and in DMs and
// groups; other channels count only when they mention you.
function updateBadge() {
  let n = 0;
  for (const c of state.convs.values()) {
    if (c.muted) continue;
    n += isVisible(c) || c.kind !== 'channel' ? unreadOf(c) : c.mentions || 0;
  }
  for (const count of Object.values(state.appBadges)) n += count;
  sb.setBadge(n);
}

// ---------- conversation pane ----------

function showPane(name) {
  for (const id of ['empty', 'chat', 'web']) $(`#${id}-pane`).hidden = id !== name;
}

function renderHeader(c) {
  const svc = SERVICES[c.service];
  $('#chat-header').replaceChildren(
    ...(MOBILE ? [h('button', { class: 'back-btn', 'aria-label': 'Back', onclick: closeConversation }, '‹')] : []),
    avatarEl(displayTitle(c), c.avatar),
    h('div', { class: 'chat-titles' },
      h('div', { class: 'chat-title' },
        h('span', {}, displayTitle(c)),
        h('button', {
          class: 'rename-btn',
          title: 'Rename this chat (only you see the new name)',
          onclick: e => {
            const titleEl = e.currentTarget.parentElement;
            titleEl.replaceChildren(inlineInput('header-rename', displayTitle(c), v => {
              if (v != null) setNickname(c.key, v);
              renderHeader(c);
              scheduleRender();
            }));
          },
        }, '✎')),
      h('div', { class: 'chat-sub' }, displayTitle(c) !== c.title ? `${c.title} · ${c.subtitle}` : c.subtitle)),
    h('span', { class: `svc-tag svc-${c.service}` }, svc?.name || c.service),
  );
  $('#composer-input').placeholder = `Message ${displayTitle(c)}`;
}

async function openConversation(key) {
  const conv = state.convs.get(key);
  if (!conv) return;
  state.openKey = key;
  state.openApp = null;
  showWebview(null);
  closeGifPanel();
  showPane('chat');
  document.body.classList.add('chat-open');
  renderHeader(conv);
  renderStaged();
  state.floatKey = !conv.muted && (conv.unread || conv.mentions) ? key : null;
  if (conv.unread || conv.mentions) {
    conv.unread = false;
    conv.mentions = 0;
    conv.unreadCount = 0;
    sb.markRead(key).catch(() => {});
  }
  scheduleRender();

  const cached = state.messages.get(key);
  if (cached) {
    renderMessages(key);
    scrollToBottom();
  } else {
    showPlaceholder('Loading…');
  }
  if (!MOBILE) $('#composer-input').focus(); // on a phone that would pop the keyboard every time

  // Always refresh: some channels (big Discord servers) don't stream live.
  try {
    const fresh = await sb.fetchMessages(key);
    state.messages.set(key, mergeMessages(state.messages.get(key), fresh));
    if (fresh.length < PAGE) state.exhausted.add(key);
    if (state.openKey === key) {
      renderMessages(key);
      scrollToBottom();
    }
  } catch (e) {
    if (state.openKey === key && !cached) showPlaceholder(cleanError(e));
    else toast(cleanError(e));
  }
}

// The latest page from the server wins (it carries reactions and edits); older
// loaded history and anything that arrived after the fetch are kept.
function mergeMessages(old = [], fresh) {
  if (!fresh.length) return old;
  const ids = new Set(fresh.map(m => m.id));
  const first = fresh[0].ts;
  const last = fresh[fresh.length - 1].ts;
  return [
    ...old.filter(m => m.ts < first && !ids.has(m.id)),
    ...fresh,
    ...old.filter(m => m.ts > last && !ids.has(m.id)),
  ];
}

const signature = list => JSON.stringify((list || []).map(m => [m.id, m.text, m.reactions?.map(r => [r.key, r.count, r.me])]));

// Re-reads the open chat quietly: after waking up, and on the phone every few
// seconds as a safety net for live updates that Android may have frozen.
async function refreshOpen() {
  const key = state.openKey;
  if (!key) return;
  try {
    const fresh = await sb.fetchMessages(key);
    if (state.openKey !== key) return;
    const before = state.messages.get(key) || [];
    const merged = mergeMessages(before, fresh);
    if (signature(merged) === signature(before)) return;
    for (const m of merged) {
      if (!before.some(b => b.id === m.id)) onMessage({ key, message: m, quiet: true });
    }
    state.messages.set(key, merged);
    const box = $('#messages');
    const top = box.scrollTop;
    renderMessages(key);
    box.scrollTop = stickToBottom ? box.scrollHeight : top;
  } catch {}
}

function showPlaceholder(text) {
  $('#messages').replaceChildren(h('div', { class: 'placeholder' }, text));
}

const RUN_GAP = 5 * 60000; // messages closer than this from one sender stack together
const TIME_GAP = 60 * 60000; // show a centered time label after a pause this long
const EMOJI_ONLY = /^[\p{Extended_Pictographic}‍️\u{1F3FB}-\u{1F3FF}\s]+$/u;

const sameRun = (a, b) => a && b && !a.system && !b.system && a.isSelf === b.isSelf &&
  a.author.id === b.author.id && b.ts - a.ts < RUN_GAP && dayKey(a.ts) === dayKey(b.ts);

const escapeRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Text with links, plus custom emoji (":name:" with an image in customEmoji).
function richText(text, customEmoji = {}) {
  const names = Object.keys(customEmoji);
  if (!names.length) return linkify(text);
  const re = new RegExp(`:(${names.map(escapeRe).join('|')}):`, 'g');
  const out = [];
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(...linkify(text.slice(last, m.index)));
    out.push(h('img', { class: 'emoji-inline', src: customEmoji[m[1]], alt: m[0], title: m[0] }));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(...linkify(text.slice(last)));
  return out;
}

// Only emoji (Unicode or custom), at most 8: shown large without a bubble.
function isEmojiOnly(text, customEmoji = {}) {
  let rest = text;
  let count = 0;
  for (const name of Object.keys(customEmoji)) {
    const pieces = rest.split(`:${name}:`);
    count += pieces.length - 1;
    rest = pieces.join('');
  }
  rest = rest.replace(/\s/g, '');
  if (rest && !EMOJI_ONLY.test(rest)) return false;
  count += [...rest].filter(ch => /\p{Extended_Pictographic}/u.test(ch)).length;
  return count > 0 && count <= 8;
}

let stickToBottom = true; // the chat is scrolled to the newest message
const mediaCache = new Map(); // ref -> blob: URL for files that need the login

function formatSize(bytes) {
  if (!bytes) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
}

function mediaUrl(key, ref) {
  if (!mediaCache.has(ref)) {
    const url = sb.fetchMedia(key, ref).then(({ data, type }) => URL.createObjectURL(new Blob([data], { type })));
    url.catch(() => mediaCache.delete(ref)); // retry next time
    mediaCache.set(ref, url);
  }
  return mediaCache.get(ref);
}

// Clicking a file: on the Mac it is saved to Downloads and opened; on the
// phone public links open in the browser.
async function openAttachment(a) {
  const key = state.openKey;
  if (!MOBILE) {
    toast(`Downloading ${a.name}…`);
    try {
      const saved = await sb.openFile(key, a);
      toast(`Saved to Downloads: ${saved.split('/').pop()}`);
    } catch (e) {
      toast(cleanError(e));
    }
  } else if (a.url) {
    sb.openExternal(a.url);
  } else {
    toast('Open this file on your Mac');
  }
}

function showLightbox(src, a) {
  const close = () => box.remove();
  const box = h('div', { class: 'lightbox', onclick: close },
    h('img', { src, alt: a.name, onclick: e => e.stopPropagation() }),
    h('div', { class: 'lightbox-bar', onclick: e => e.stopPropagation() },
      h('span', { class: 'lightbox-name' }, a.name, a.size ? ` · ${formatSize(a.size)}` : ''),
      MOBILE && !a.url ? null : h('button', { class: 'btn small', onclick: () => openAttachment(a) }, MOBILE ? 'Open' : 'Save to Downloads'),
      h('button', { class: 'btn small', onclick: close }, 'Close')));
  document.body.append(box);
}

function fileChip(a) {
  return h('a', {
    class: 'bubble file',
    href: '#',
    title: MOBILE ? null : 'Save to Downloads and open',
    onclick: e => { e.preventDefault(); openAttachment(a); },
  },
  h('span', { class: 'file-icon' }, '📄'),
  h('span', { class: 'file-meta' }, h('span', { class: 'file-name' }, a.name), a.size ? h('span', { class: 'file-size' }, formatSize(a.size)) : null));
}

function mediaEl(a) {
  const key = state.openKey;
  if (a.isVideo) {
    const video = h('video', { class: 'bubble-image', src: a.url, poster: a.poster, loop: true, autoplay: true, playsinline: true, onclick: () => openAttachment(a) });
    video.muted = true; // must be the property, or autoplay is refused
    return video;
  }
  if (!a.isImage) return fileChip(a);
  const img = h('img', { class: 'bubble-image', alt: a.name, title: a.name });
  img.addEventListener('click', () => img.src && showLightbox(img.src, a));
  if (a.url && !a.ref) {
    img.src = a.url;
  } else if (a.thumbRef || a.ref) {
    img.classList.add('loading');
    mediaUrl(key, a.thumbRef || a.ref)
      .then(url => {
        img.src = url;
        img.classList.remove('loading');
      })
      .catch(() => img.replaceWith(fileChip(a)));
  }
  return img;
}

// ----- sending files -----

// Pasted, dropped or picked files wait in a tray above the message box until
// the message is sent (Enter or the send button). Kept per chat.
const stagedFiles = new Map(); // conversation key -> [File]
const previewUrls = new WeakMap(); // File -> blob: URL for its thumbnail

function stageFiles(fileList) {
  const key = state.openKey;
  const files = [...(fileList || [])];
  if (!key || !files.length) return;
  const big = files.find(f => f.size > 50 * 1024 * 1024);
  if (big) return toast(`${big.name || 'That file'} is too large (50 MB at most)`);
  stagedFiles.set(key, [...(stagedFiles.get(key) || []), ...files]);
  renderStaged();
  $('#composer-input').focus();
}

function unstage(key, file) {
  const rest = (stagedFiles.get(key) || []).filter(f => f !== file);
  if (previewUrls.has(file)) URL.revokeObjectURL(previewUrls.get(file));
  if (rest.length) stagedFiles.set(key, rest);
  else stagedFiles.delete(key);
  renderStaged();
}

function renderStaged() {
  const key = state.openKey;
  const files = stagedFiles.get(key) || [];
  const tray = $('#staged');
  tray.hidden = !files.length;
  tray.replaceChildren(
    ...files.map(f => {
      let preview;
      if (/^image\//.test(f.type)) {
        if (!previewUrls.has(f)) previewUrls.set(f, URL.createObjectURL(f));
        preview = h('img', { src: previewUrls.get(f), alt: '' });
      } else {
        preview = h('span', { class: 'staged-icon' }, '📄');
      }
      return h('div', { class: 'staged-file', title: f.name || 'Pasted image' },
        preview,
        h('div', { class: 'staged-meta' }, h('span', { class: 'staged-name' }, f.name || 'Pasted image'), h('span', {}, formatSize(f.size))),
        h('button', { class: 'staged-remove', title: 'Remove', 'aria-label': 'Remove', onclick: () => unstage(key, f) }, '✕'));
    }),
    files.length ? h('div', { class: 'staged-hint' }, MOBILE ? 'Tap send to share' : 'Press Enter to send · Esc to remove all') : null);
}

async function sendStaged() {
  const key = state.openKey;
  const files = stagedFiles.get(key) || [];
  stagedFiles.delete(key);
  renderStaged();
  const ok = await sendFiles(files);
  if (!ok && files.length) {
    stagedFiles.set(key, [...files, ...(stagedFiles.get(key) || [])]); // put them back to retry
    if (state.openKey === key) renderStaged();
  }
}

async function sendFiles(files) {
  const key = state.openKey;
  if (!key || !files.length) return false;
  const input = $('#composer-input');
  const text = input.value.trim();
  input.value = '';
  autosize();
  toast(`Sending ${files.length === 1 ? files[0].name || 'image' : `${files.length} files`}…`);
  try {
    const payload = await Promise.all(files.map(async (f, i) => ({
      name: f.name || `pasted-${Date.now()}-${i}.${(f.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`,
      type: f.type,
      data: new Uint8Array(await f.arrayBuffer()),
    })));
    const message = await sb.upload(key, payload, text);
    if (message) onMessage({ key, message });
    else setTimeout(refreshOpen, 1500); // Slack: the message arrives over the socket
    toast('Sent');
    scrollToBottom();
    return true;
  } catch (e) {
    if (text && !input.value) input.value = text;
    autosize();
    toast(cleanError(e));
    return false;
  }
}

function reactionChips(m) {
  if (!m.reactions?.length) return null;
  return h('div', { class: 'reactions' }, ...m.reactions.map(r => h('button', {
    class: `reaction${r.me ? ' mine' : ''}`,
    title: r.me ? 'Remove your reaction' : `React with ${r.emoji || `:${r.name}:`}`,
    onclick: e => { e.stopPropagation(); react(m, r.key, !r.me); },
  },
  r.imageUrl ? h('img', { src: r.imageUrl, alt: r.name }) : (r.emoji || `:${r.name}:`),
  h('span', {}, r.count))));
}

function bubbleEl(m, { last, showName, showAvatar }) {
  const parts = [];
  if (m.text) {
    const emoji = isEmojiOnly(m.text, m.customEmoji);
    parts.push(h('div', { class: `bubble${emoji ? ' emoji' : ''}${m.mentionsMe && !m.isSelf ? ' mention' : ''}` }, ...richText(m.text, m.customEmoji)));
  }
  for (const a of m.attachments || []) parts.push(mediaEl(a));
  if (last && parts.length) parts[parts.length - 1].classList.add('tail');
  const label = [showName ? m.author.name : null, m.isReply ? 'reply in thread' : null].filter(Boolean).join(' · ');
  if (m.replyTo) {
    parts.unshift(h('div', {
      class: 'reply-quote',
      title: m.replyTo.id ? 'Show the original message' : null,
      onclick: () => jumpToMessage(m.replyTo.id),
    },
    m.replyTo.author ? h('span', { class: 'reply-author' }, `↪ ${m.replyTo.author} `) : '↪ ',
    m.replyTo.text));
  }
  const stack = h('div', {
    class: 'msg-stack',
    ondblclick: e => {
      window.getSelection()?.removeAllRanges();
      openReactionPicker(m, e.currentTarget);
    },
    oncontextmenu: e => {
      e.preventDefault();
      openReactionPicker(m, e.currentTarget);
    },
  },
  label ? h('div', { class: 'msg-name' }, label) : null,
  ...parts,
  reactionChips(m));
  const reactBtn = MOBILE ? null : h('button', {
    class: 'react-btn',
    title: 'React',
    onclick: e => { e.stopPropagation(); openReactionPicker(m, stack); },
  }, '☺︎');
  return h('div', { class: `msg-row ${m.isSelf ? 'me' : 'them'}${last ? ' last' : ''}`, 'data-id': m.id, title: formatTime(m.ts) },
    showAvatar ? (last ? avatarEl(m.author.name, m.author.avatar, 'msg-avatar') : h('div', { class: 'msg-avatar' })) : null,
    m.isSelf ? reactBtn : null,
    stack,
    m.isSelf ? null : reactBtn);
}

// ----- reactions -----

const QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🙏'];

function closePicker() {
  document.querySelector('.react-picker')?.remove();
}

function openReactionPicker(m, anchor) {
  closePicker();
  const picker = h('div', { class: 'react-picker', onclick: e => e.stopPropagation() },
    ...QUICK_REACTIONS.map(emoji => {
      const mine = m.reactions?.find(r => r.emoji === emoji && r.me);
      return h('button', {
        class: mine ? 'on' : null,
        title: mine ? 'Remove your reaction' : `React with ${emoji}`,
        onclick: () => {
          closePicker();
          react(m, mine ? mine.key : emoji, !mine);
        },
      }, emoji);
    }),
    m.text ? h('button', { class: 'copy', onclick: () => { sb.copyText(m.text); closePicker(); toast('Copied'); } }, 'Copy') : null);
  document.body.append(picker);
  const box = anchor.getBoundingClientRect();
  const width = picker.offsetWidth;
  picker.style.top = `${Math.max(8, box.top - picker.offsetHeight - 6)}px`;
  picker.style.left = `${Math.min(window.innerWidth - width - 8, Math.max(8, m.isSelf ? box.right - width : box.left))}px`;
  setTimeout(() => document.addEventListener('click', closePicker, { once: true }));
}

async function react(m, value, add) {
  const key = state.openKey;
  try {
    const info = await sb.react(key, m.id, value, add);
    applyReaction(key, m.id, info, true, add ? 1 : -1);
  } catch (e) {
    toast(cleanError(e));
  }
}

// Own reactions are idempotent (the server echoes them back), others' add up.
function applyReaction(convKey, messageId, info, mine, delta) {
  const m = state.messages.get(convKey)?.find(x => x.id === messageId);
  if (!m) return;
  m.reactions ||= [];
  let r = m.reactions.find(x => x.key === info.key);
  if (mine && (delta > 0 ? r?.me : !r?.me)) return;
  if (!r) {
    if (delta < 0) return;
    r = { ...info, count: 0, me: false };
    m.reactions.push(r);
  }
  r.count += delta;
  if (mine) r.me = delta > 0;
  if (r.count <= 0) m.reactions.splice(m.reactions.indexOf(r), 1);
  if (convKey === state.openKey) {
    const box = $('#messages');
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    const top = box.scrollTop;
    renderMessages(convKey);
    box.scrollTop = atBottom ? box.scrollHeight : top;
  }
}

// ----- GIFs -----

let gifSearchTimer;

function closeGifPanel() {
  $('#gif-panel').hidden = true;
  $('#gif-panel').replaceChildren();
}

function openGifPanel() {
  const panel = $('#gif-panel');
  if (!panel.hidden) return closeGifPanel();
  const grid = h('div', { class: 'gif-grid' });
  const input = h('input', { type: 'search', placeholder: 'Search GIFs', spellcheck: 'false' });
  const load = async query => {
    grid.replaceChildren(h('div', { class: 'placeholder' }, 'Loading…'));
    try {
      const gifs = await sb.searchGifs(query);
      if (input.value.trim() !== query) return; // a newer search is on its way
      grid.replaceChildren(...(gifs.length ? gifs.slice(0, 40).map(g => {
        const video = h('video', { src: g.preview, loop: true, autoplay: true, playsinline: true, title: 'Send this GIF', onclick: () => sendGif(g) });
        video.muted = true;
        return video;
      }) : [h('div', { class: 'placeholder' }, 'No GIFs found')]));
    } catch (e) {
      grid.replaceChildren(h('div', { class: 'placeholder' }, cleanError(e)));
    }
  };
  input.addEventListener('input', () => {
    clearTimeout(gifSearchTimer);
    gifSearchTimer = setTimeout(() => load(input.value.trim()), 350);
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      closeGifPanel();
    }
  });
  panel.replaceChildren(h('div', { class: 'gif-head' }, input, h('button', { class: 'icon-btn', title: 'Close', onclick: closeGifPanel }, '✕')), grid);
  panel.hidden = false;
  if (!MOBILE) input.focus();
  load('');
}

// Discord embeds its own Tenor links; elsewhere the direct .gif link previews as an image.
async function sendGif(g) {
  const key = state.openKey;
  const conv = state.convs.get(key);
  if (!conv) return;
  closeGifPanel();
  const discord = conv.service === 'discord';
  try {
    const message = await sb.send(key, discord ? g.url : g.gif);
    message.text = '';
    message.attachments = [discord ? { name: 'GIF', url: g.preview, isVideo: true } : { name: 'GIF', url: g.gif, isImage: true }];
    onMessage({ key, message });
    scrollToBottom();
  } catch (e) {
    toast(cleanError(e));
  }
}

function jumpToMessage(id) {
  const row = id && [...document.querySelectorAll('#messages .msg-row')].find(el => el.dataset.id === id);
  if (!row) return toast('The original message is further back; scroll up to load it');
  row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  row.classList.remove('flash');
  void row.offsetWidth; // restart the animation
  row.classList.add('flash');
}

function renderMessages(key) {
  const list = state.messages.get(key) || [];
  if (!list.length) return showPlaceholder('No messages yet');
  const group = state.convs.get(key)?.kind !== 'dm'; // names and avatars only where several people talk
  const nodes = [];
  if (state.exhausted.has(key)) nodes.push(h('div', { class: 'history-start' }, 'Beginning of conversation'));
  list.forEach((m, i) => {
    const prev = list[i - 1];
    if (!prev || dayKey(prev.ts) !== dayKey(m.ts) || m.ts - prev.ts > TIME_GAP) {
      nodes.push(h('div', { class: 'time-sep' }, h('b', {}, formatDay(m.ts)), ` ${formatTime(m.ts)}`));
    }
    if (m.system) {
      nodes.push(h('div', { class: 'system-msg' }, m.text));
      return;
    }
    const first = !sameRun(prev, m);
    nodes.push(bubbleEl(m, {
      last: !sameRun(m, list[i + 1]),
      showName: group && !m.isSelf && first,
      showAvatar: group && !m.isSelf,
    }));
    if (first) nodes[nodes.length - 1].classList.add('first');
  });
  $('#messages').replaceChildren(...nodes);
}

function scrollToBottom() {
  const box = $('#messages');
  box.scrollTop = box.scrollHeight;
}

async function loadOlder() {
  const key = state.openKey;
  const list = state.messages.get(key);
  if (!key || !list?.length || state.loadingOlder || state.exhausted.has(key)) return;
  state.loadingOlder = true;
  try {
    const older = await sb.fetchMessages(key, list[0].id);
    if (older.length < PAGE) state.exhausted.add(key);
    const ids = new Set(list.map(m => m.id));
    list.unshift(...older.filter(m => !ids.has(m.id)));
    if (state.openKey === key) {
      const box = $('#messages');
      const fromBottom = box.scrollHeight - box.scrollTop;
      renderMessages(key);
      box.scrollTop = box.scrollHeight - fromBottom;
    }
  } catch (e) {
    toast(cleanError(e));
  } finally {
    state.loadingOlder = false;
  }
}

function onMessage({ key, message, counts, quiet = false }) {
  const conv = state.convs.get(key);
  if (!conv) return;
  conv.lastActivity = Math.max(conv.lastActivity || 0, message.ts);
  const list = state.messages.get(key);
  const isNew = !list?.some(m => m.id === message.id);
  if (list && isNew) list.push(message);

  if (key === state.openKey && list) {
    const box = $('#messages');
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
    renderMessages(key);
    if (nearBottom || message.isSelf) scrollToBottom();
  }

  if (isNew && !message.isSelf && !conv.muted) {
    if (key === state.openKey && document.hasFocus()) {
      sb.markRead(key).catch(() => {});
    } else {
      if (counts) {
        Object.assign(conv, counts); // the provider has already counted it
      } else {
        conv.unread = true;
        conv.unreadCount = (conv.unreadCount || 0) + 1;
        if (message.mentionsMe) conv.mentions = (conv.mentions || 0) + 1;
      }
      if (!quiet && (conv.kind !== 'channel' || message.mentionsMe)) notify(conv, message);
    }
  }
  scheduleRender();
}

function closeConversation() {
  state.openKey = null;
  document.body.classList.remove('chat-open');
  showPane('empty');
  scheduleRender();
}

function notify(conv, message) {
  if (MOBILE || !('Notification' in window)) return;
  const title = conv.kind === 'dm'
    ? state.view.nicknames.get(conv.key) || message.author.name
    : `${message.author.name} in ${displayTitle(conv)}`;
  const n = new Notification(title, { body: message.text || 'Sent an attachment', silent: false });
  n.onclick = () => {
    sb.focus();
    openConversation(conv.key);
  };
}

async function sendMessage() {
  const input = $('#composer-input');
  const text = input.value.trim();
  const key = state.openKey;
  if (key && stagedFiles.get(key)?.length) return sendStaged();
  if (!text || !key) return;
  input.value = '';
  autosize();
  try {
    onMessage({ key, message: await sb.send(key, text) });
    scrollToBottom();
  } catch (e) {
    if (!input.value) input.value = text;
    autosize();
    toast(cleanError(e));
  }
}

function autosize() {
  const input = $('#composer-input');
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
}

// ---------- web apps ----------

function syncWebviews() {
  const box = $('#webapps');
  const apps = state.settings.webApps;
  const ids = new Set(apps.map(a => a.id));
  for (const wv of [...box.children]) {
    if (!ids.has(wv.dataset.id)) wv.remove();
  }
  for (const app of apps) {
    if ([...box.children].some(wv => wv.dataset.id === app.id)) continue;
    const wv = document.createElement('webview');
    wv.dataset.id = app.id;
    wv.setAttribute('partition', `persist:webapp-${app.id}`);
    wv.setAttribute('useragent', state.settings.userAgent);
    wv.setAttribute('allowpopups', '');
    wv.setAttribute('src', app.url);
    wv.addEventListener('page-title-updated', e => {
      const m = /\((\d+)\)/.exec(e.title);
      state.appBadges[app.id] = m ? Number(m[1]) : 0;
      scheduleRender();
    });
    box.append(wv);
  }
  if (state.openApp && !ids.has(state.openApp)) {
    state.openApp = null;
    showPane('empty');
  }
}

function showWebview(id) {
  for (const wv of $('#webapps').children) wv.classList.toggle('shown', wv.dataset.id === id);
}

function openApp(id) {
  const app = state.settings.webApps.find(a => a.id === id);
  if (!app) return;
  state.openApp = id;
  state.openKey = null;
  const reload = () => [...$('#webapps').children].find(wv => wv.dataset.id === id)?.loadURL(app.url);
  $('#web-bar').replaceChildren(
    h('span', { class: 'web-title' }, app.name),
    h('button', { class: 'btn small web-reload', title: 'Start this web app over from its home page', onclick: reload }, '↻ Reload'),
  );
  showPane('web');
  showWebview(id);
  scheduleRender();
}

// ---------- settings ----------

function statusLine(id) {
  const s = state.statuses[id];
  if (!s || s.state === 'off') return null;
  const text = s.state === 'connected' ? `Connected${s.user ? ` as ${s.user}` : ''}` : s.error || (s.state === 'connecting' ? 'Connecting…' : s.state);
  return h('div', { class: `state-line${s.state === 'error' ? ' error' : ''}` }, text);
}

async function run(btn, fn) {
  btn.disabled = true;
  try {
    const next = await fn();
    if (next) state.settings = next;
    renderSettings();
    syncWebviews();
    scheduleRender();
  } catch (e) {
    toast(cleanError(e));
    btn.disabled = false;
  }
}

function discordSection() {
  const s = state.settings;
  const input = h('input', { type: 'password', placeholder: s.hasDiscord ? 'Paste a new token to replace it' : 'Paste your Discord token', autocomplete: 'off' });
  const save = h('button', { class: 'btn primary', onclick: () => run(save, () => sb.setDiscordToken(input.value)) }, s.hasDiscord ? 'Replace' : 'Connect');
  const remove = h('button', { class: 'btn danger', onclick: () => run(remove, () => sb.removeDiscord()) }, 'Disconnect');
  return h('section', {},
    h('h3', {}, h('span', { class: 'svc-badge svc-discord', style: 'position:static' }, 'D'), 'Discord'),
    statusLine('discord'),
    h('div', { class: 'row' }, input, save, s.hasDiscord ? remove : null),
    h('details', {},
      h('summary', {}, 'How to get your token'),
      h('ol', {},
        h('li', {}, 'Open ', h('code', {}, 'discord.com/app'), ' in Chrome and log in.'),
        h('li', {}, 'Press ', h('code', {}, '⌥⌘I'), ', open the Network tab, then click any channel.'),
        h('li', {}, 'Click a request to ', h('code', {}, 'discord.com/api'), ' and copy the ', h('code', {}, 'authorization'), ' request header value.')),
      h('p', { class: 'warn' }, 'Using a user token in a third-party client is against Discord\'s terms and carries a small risk of account action. Your token is stored encrypted with your macOS Keychain. Changing your Discord password invalidates it.')));
}

function mattermostSection() {
  const s = state.settings;
  const url = h('input', { type: 'url', value: s.mattermostUrl || '', placeholder: 'https://mattermost.example.org' });
  const sso = h('button', { class: 'btn primary', onclick: () => run(sso, () => sb.mattermostBrowserLogin(url.value)) }, s.hasMattermost ? 'Sign in again' : 'Sign in with browser');
  const remove = h('button', { class: 'btn danger', onclick: () => run(remove, () => sb.removeMattermost()) }, 'Disconnect');
  const pat = h('input', { type: 'password', placeholder: 'Personal access token', autocomplete: 'off' });
  const patSave = h('button', { class: 'btn', onclick: () => run(patSave, () => sb.setMattermostToken(url.value, pat.value)) }, 'Use token');
  return h('section', {},
    h('h3', {}, h('span', { class: 'svc-badge svc-mattermost', style: 'position:static' }, 'M'), 'Mattermost'),
    statusLine('mattermost'),
    h('div', { class: 'row' }, url),
    h('div', { class: 'row' }, sso, s.hasMattermost ? remove : null),
    h('p', {}, 'Opens your server\'s normal login page (CERN SSO works). The window closes by itself once you are in.'),
    h('details', {},
      h('summary', {}, 'Use a personal access token instead'),
      h('div', { class: 'row' }, pat, patSave)));
}

const SLACK_MANIFEST = `display_information:
  name: Switchboard
  description: Personal Slack access for the Switchboard desktop app
oauth_config:
  scopes:
    user:
      - channels:history
      - channels:read
      - channels:write
      - chat:write
      - files:read
      - files:write
      - groups:history
      - groups:read
      - groups:write
      - im:history
      - im:read
      - im:write
      - mpim:history
      - mpim:read
      - mpim:write
      - reactions:read
      - reactions:write
      - users:read
settings:
  event_subscriptions:
    user_events:
      - message.channels
      - message.groups
      - message.im
      - message.mpim
      - reaction_added
      - reaction_removed
  socket_mode_enabled: true
  org_deploy_enabled: false
  token_rotation_enabled: false
`;

const extLink = (text, url) => h('a', { href: '#', onclick: e => { e.preventDefault(); sb.openExternal(url); } }, text);

function slackSection() {
  const accounts = state.settings.slack || [];
  const userToken = h('input', { type: 'password', placeholder: 'User OAuth Token (xoxp-…)', autocomplete: 'off' });
  const appToken = h('input', { type: 'password', placeholder: 'App-level token (xapp-…)', autocomplete: 'off' });
  const add = h('button', { class: 'btn primary', onclick: () => run(add, () => sb.addSlack(userToken.value, appToken.value)) }, 'Add workspace');
  const copy = h('button', { class: 'btn small', onclick: () => { sb.copyText(SLACK_MANIFEST); toast('Manifest copied'); } }, 'Copy manifest');
  const rows = accounts.map(a => {
    const remove = h('button', { class: 'btn danger', onclick: () => run(remove, () => sb.removeSlack(a.id)) }, 'Disconnect');
    return h('div', { class: 'row' }, h('div', { style: 'flex:1;min-width:0' }, h('div', {}, a.name), statusLine(`slack-${a.id}`)), remove);
  });
  return h('section', {},
    h('h3', {}, h('span', { class: 'svc-badge svc-slack', style: 'position:static' }, 'S'), 'Slack'),
    ...rows,
    h('details', { open: accounts.length ? null : true },
      h('summary', {}, accounts.length ? 'Add another workspace' : 'How to connect a workspace'),
      h('ol', {},
        h('li', {}, copy, ' then open ', extLink('api.slack.com/apps', 'https://api.slack.com/apps'), '.'),
        h('li', {}, 'Create New App → From a manifest → pick your workspace → paste → Create.'),
        h('li', {}, 'Click Install to Workspace and Allow. Under OAuth & Permissions, copy the User OAuth Token.'),
        h('li', {}, 'Under Basic Information → App-Level Tokens, click Generate, add the connections:write scope, and copy the token.')),
      h('div', { class: 'row' }, userToken),
      h('div', { class: 'row' }, appToken, add),
      h('p', {}, 'This creates your own private app inside the workspace; nothing is shared with anyone else. Some workspaces need an admin to approve new apps. Repeat for each workspace.')));
}

// The code display outlives Settings re-renders (they happen on every status
// change), so the box and its cycling timer are kept here.
const setupUi = { box: null, cycle: null };

function phoneSection() {
  const box = (setupUi.box ||= h('div'));
  const hide = () => {
    clearInterval(setupUi.cycle);
    box.replaceChildren();
    show.disabled = false;
  };
  const showCode = async part => {
    try {
      clearInterval(setupUi.cycle);
      const { dataUrls, dropped } = await sb.phoneSetupCode(part);
      const accounts = part === 'accounts';
      const img = h('img', { class: 'setup-qr', src: dataUrls[0], alt: 'Phone setup code' });
      const counter = h('div', { class: 'state-line', style: 'text-align:center' });
      if (dataUrls.length > 1) {
        let i = 0;
        const flip = () => {
          img.src = dataUrls[i];
          counter.textContent = `Part ${i + 1} of ${dataUrls.length}. Keep the phone pointed here until it finishes.`;
          i = (i + 1) % dataUrls.length;
        };
        flip();
        setupUi.cycle = setInterval(flip, 1300);
      }
      box.replaceChildren(
        h('div', { class: 'setup-step' }, accounts ? 'Code 1 of 2: accounts' : 'Code 2 of 2: groups and nicknames'),
        img,
        counter,
        accounts
          ? h('p', { class: 'warn' }, 'This code contains your account logins. Scan it only with your own phone, and don\'t screenshot or share it.')
          : h('p', {}, 'Optional: copies your groups, nicknames and hidden chats.'),
        dropped.length ? h('p', {}, `Too much to fit, so these stay on the Mac: ${dropped.join(', ')}.`) : null,
        h('div', { class: 'row' },
          accounts ? h('button', { class: 'btn primary', onclick: () => showCode('layout') }, 'Next: groups and nicknames') : null,
          h('button', { class: 'btn', onclick: hide }, accounts ? 'Done' : 'Hide code')));
    } catch (e) {
      toast(cleanError(e));
      show.disabled = false;
    }
  };
  const show = h('button', { class: 'btn', disabled: box.hasChildNodes(), onclick: () => { show.disabled = true; showCode('accounts'); } }, 'Show setup code');
  return h('section', {},
    h('h3', {}, 'Set up phone'),
    h('p', {}, 'In Switchboard on your Pixel, tap Scan setup code and point it at the code. The first code copies your accounts; the second (optional) copies your groups and nicknames.'),
    h('div', { class: 'row' }, show),
    box);
}

function appearanceSection() {
  return h('section', {},
    h('h3', {}, 'Appearance'),
    h('label', { class: 'edit-new' },
      h('input', { type: 'checkbox', checked: state.view.compact, onchange: e => setCompact(e.target.checked) }),
      'Compact chat list'),
    h('label', { class: 'edit-new' },
      h('input', { type: 'checkbox', checked: state.view.flat, onchange: e => setFlat(e.target.checked) }),
      'Latest first (ignore groups; newest message at the top)'),
    MOBILE
      ? h('p', {}, 'Long-press a chat to put it in a group, rename it or hide it.')
      : h('p', {}, 'Organize the list by right-clicking a chat (Move to group), dragging a chat onto a group, or clicking + New group at the bottom of the list.'),
    MOBILE ? null : h('p', {}, 'Ctrl+J / Ctrl+K move down and up through the list. Ctrl+L toggles latest first. ⌘K searches.'));
}

function webAppsSection() {
  const apps = state.settings.webApps;
  const rows = apps.map(app => {
    const remove = h('button', { class: 'btn danger', onclick: () => run(remove, () => sb.setWebApps(apps.filter(a => a.id !== app.id))) }, 'Remove');
    return h('div', { class: 'row' }, h('div', { style: 'flex:1;min-width:0' }, h('div', {}, app.name), h('div', { class: 'state-line' }, app.url)), remove);
  });
  const name = h('input', { placeholder: 'Name, e.g. Teams (work)' });
  const url = h('input', { type: 'url', placeholder: 'https://teams.microsoft.com/v2/' });
  const add = h('button', {
    class: 'btn',
    onclick: () => run(add, () => {
      const id = `${name.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'app'}-${Date.now().toString(36)}`;
      return sb.setWebApps([...apps, { id, name: name.value || 'Web app', service: /teams/.test(url.value) ? 'teams' : 'web', url: url.value }]);
    }),
  }, 'Add');
  return h('section', {},
    h('h3', {}, h('span', { class: 'svc-badge svc-teams', style: 'position:static' }, 'T'), 'Teams and other web apps'),
    h('p', {}, 'Each one runs the real web app with its own separate login, so a personal and a UF account can be signed in at once. Unread counts come from the page title.'),
    ...rows,
    h('div', { class: 'row' }, name, url, add));
}

function phoneAccountsSection() {
  const connected = Object.values(state.statuses).filter(s => s.state !== 'off');
  const scan = h('button', {
    class: 'btn primary',
    onclick: async () => {
      scan.disabled = true;
      try {
        const kind = await sb.scanSetup();
        if (kind === 'layout') return location.reload();
        toast('Accounts added. For your groups and nicknames, click Next on the Mac and scan again.');
        scan.disabled = false;
      } catch (e) {
        toast(cleanError(e));
        scan.disabled = false;
      }
    },
  }, 'Scan setup code');
  const remove = h('button', { class: 'btn danger', onclick: async () => { await sb.removeAll(); location.reload(); } }, 'Remove all accounts');
  return h('section', {},
    h('h3', {}, 'Accounts'),
    ...connected.map(s => h('div', { class: 'row' }, h('div', { style: 'flex:1;min-width:0' }, h('div', {}, s.label), statusLine(s.provider)))),
    connected.length ? null : h('p', {}, 'No accounts on this phone yet.'),
    h('p', {}, 'On your Mac, open Switchboard → Settings → Set up phone → Show setup code, then scan it here. Scan the second code too to copy your groups and nicknames. Scanning accounts again replaces them.'),
    h('div', { class: 'row' }, scan, connected.length ? remove : null));
}

function renderSettings() {
  const s = state.settings;
  const children = [h('h2', {}, MOBILE ? 'Settings' : 'Accounts')];
  if (MOBILE) children.push(phoneAccountsSection());
  else if (s.demo) children.push(h('p', {}, 'Demo mode: showing sample conversations. Run the app normally to connect real accounts.'));
  else children.push(discordSection(), mattermostSection(), slackSection(), webAppsSection(), phoneSection());
  children.push(appearanceSection());
  children.push(h('div', { class: 'dialog-actions' }, h('button', { class: 'btn', onclick: closeSettings }, 'Done')));
  $('#settings .dialog').replaceChildren(...children);
}

function openSettings() {
  renderSettings();
  $('#settings').hidden = false;
}

function closeSettings() {
  $('#settings').hidden = true;
  clearInterval(setupUi.cycle);
  setupUi.box?.replaceChildren();
}

// ---------- keyboard navigation ----------

// Ctrl+J / Ctrl+K step through the sidebar in on-screen order (web apps first,
// then chats; chats inside collapsed groups are skipped).
function hotkey(action) {
  if (action === 'next') navigate(1);
  else if (action === 'prev') navigate(-1);
  else if (action === 'flat') setFlat(!state.view.flat, true);
  else if (action === 'refresh') refreshOpen();
  else if (action === 'back') {
    // Android back button: close whatever is on top, else leave the app.
    if (!$('#settings').hidden) closeSettings();
    else if (state.renamingConv || state.renaming) document.activeElement?.blur();
    else if (state.editing) setEditing(false);
    else if (state.openKey) closeConversation();
    else sb.exit?.();
  }
}

// ----- search: Enter opens the highlighted match (the first, or the one
// picked with Ctrl+J / Ctrl+K or the arrow keys) -----

const searching = () => !!state.query.trim() && !state.editing;
const searchMatches = () => [...document.querySelectorAll('#convs .conv')].map(el => el.dataset.key).filter(Boolean);

function markSearchPick() {
  const keys = searching() ? searchMatches() : [];
  if (!keys.includes(state.searchKey)) state.searchKey = keys[0] || null;
  for (const el of document.querySelectorAll('#convs .conv')) {
    el.classList.toggle('picked', !!state.searchKey && el.dataset.key === state.searchKey);
  }
}

function movePick(delta) {
  const keys = searchMatches();
  if (!keys.length) return;
  const i = keys.indexOf(state.searchKey);
  state.searchKey = keys[Math.min(keys.length - 1, Math.max(0, i + delta))];
  markSearchPick();
  document.querySelector('#convs .conv.picked')?.scrollIntoView({ block: 'nearest' });
}

function clearSearch() {
  state.query = '';
  state.searchKey = null;
  $('#search').value = '';
  $('#search').blur();
  renderSidebar();
}

function openPick() {
  const key = state.searchKey;
  if (!key) return;
  clearSearch();
  openConversation(key);
  requestAnimationFrame(() => document.querySelector('#sidebar .conv.active')?.scrollIntoView({ block: 'nearest' }));
}

function navigate(delta) {
  if (state.editing || state.renaming || state.renamingConv) return;
  const order = [...document.querySelectorAll('#apps .conv, #convs .conv')].map(el => el.dataset.key).filter(Boolean);
  if (!order.length) return;
  const current = state.openApp ? `app:${state.openApp}` : state.openKey;
  const i = order.indexOf(current);
  const next = order[i === -1 ? (delta > 0 ? 0 : order.length - 1) : Math.min(order.length - 1, Math.max(0, i + delta))];
  if (next === current) return;
  if (next.startsWith('app:')) openApp(next.slice(4));
  else openConversation(next);
  requestAnimationFrame(() => document.querySelector('#sidebar .conv.active')?.scrollIntoView({ block: 'nearest' }));
}

// ---------- startup ----------

function bindUi() {
  $('#search').addEventListener('input', e => {
    state.query = e.target.value;
    state.searchKey = null; // a new search starts at the first match
    renderSidebar();
  });
  $('#search').addEventListener('keydown', e => {
    if (e.isComposing) return;
    if (e.key === 'Enter') {
      e.preventDefault();
      openPick();
    } else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && searching()) {
      e.preventDefault();
      movePick(e.key === 'ArrowDown' ? 1 : -1);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      clearSearch();
    }
  });
  $('#settings-btn').addEventListener('click', openSettings);
  $('#compact-btn').addEventListener('click', () => setCompact(!state.view.compact));
  $('#flat-btn').addEventListener('click', () => setFlat(!state.view.flat));
  $('#edit-btn').addEventListener('click', () => setEditing(true));
  $('#settings').addEventListener('click', e => {
    if (e.target.id === 'settings') closeSettings();
  });
  $('#gif-btn').addEventListener('click', openGifPanel);
  $('#composer').addEventListener('submit', e => {
    e.preventDefault();
    sendMessage();
  });
  const input = $('#composer-input');
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape' && stagedFiles.has(state.openKey)) {
      e.stopPropagation();
      for (const f of [...stagedFiles.get(state.openKey)]) unstage(state.openKey, f);
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !MOBILE) {
      e.preventDefault();
      sendMessage();
    }
  });
  $('#messages').addEventListener('scroll', e => {
    const box = e.target;
    stickToBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    if (box.scrollTop < 150) loadOlder();
  });
  // When the list gets shorter (phone keyboard opening, window resizing), keep
  // the newest message in view if it was in view before.
  new ResizeObserver(() => {
    if (stickToBottom) scrollToBottom();
  }).observe($('#messages'));
  $('#composer-input').addEventListener('focus', () => {
    if (MOBILE) setTimeout(scrollToBottom, 350);
  });
  $('#attach-btn').addEventListener('click', () => $('#file-input').click());
  $('#file-input').addEventListener('change', e => {
    stageFiles(e.target.files);
    e.target.value = '';
  });
  $('#composer-input').addEventListener('paste', e => {
    if (e.clipboardData?.files?.length) {
      e.preventDefault();
      stageFiles(e.clipboardData.files);
    }
  });
  const pane = $('#chat-pane');
  const hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
  pane.addEventListener('dragover', e => {
    if (!hasFiles(e) || !state.openKey) return;
    e.preventDefault();
    pane.classList.add('file-drop');
  });
  pane.addEventListener('dragleave', e => {
    if (!pane.contains(e.relatedTarget)) pane.classList.remove('file-drop');
  });
  pane.addEventListener('drop', e => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    pane.classList.remove('file-drop');
    stageFiles(e.dataTransfer.files);
  });
  if (MOBILE) {
    setInterval(() => {
      if (document.visibilityState === 'visible') refreshOpen();
    }, 10000);
  }
  document.addEventListener('keydown', e => {
    const action = { KeyJ: 'next', KeyK: 'prev', KeyL: 'flat' }[e.code];
    if (e.ctrlKey && !e.metaKey && !e.altKey && !e.isComposing && action) {
      e.preventDefault();
      if (document.activeElement === $('#search') && searching() && action !== 'flat') movePick(action === 'next' ? 1 : -1);
      else hotkey(action);
    } else if (e.metaKey && e.key === 'k') {
      e.preventDefault();
      $('#search').focus();
      $('#search').select();
    } else if (e.metaKey && e.key === ',') {
      e.preventDefault();
      openSettings();
    } else if (e.key === 'Escape' && !$('#settings').hidden) {
      closeSettings();
    } else if (e.key === 'Escape' && state.editing) {
      setEditing(false);
    }
  });
  window.addEventListener('focus', () => {
    const conv = state.convs.get(state.openKey);
    if (conv && (conv.unread || conv.mentions)) {
      conv.unread = false;
      conv.mentions = 0;
      conv.unreadCount = 0;
      sb.markRead(conv.key).catch(() => {});
      scheduleRender();
    }
  });
}

async function init() {
  if (MOBILE) {
    document.body.classList.add('mobile');
    $('#search').placeholder = 'Search';
  }
  const initial = await sb.getState();
  state.settings = initial.settings;
  state.statuses = initial.statuses;
  const v = initial.settings.view || {};
  state.view = {
    mode: v.mode || 'all',
    keys: new Set(v.keys || []),
    groups: v.groups || [],
    assign: new Map(Object.entries(v.assign || {})),
    nicknames: new Map(Object.entries(v.nicknames || {})),
    pins: Array.isArray(v.pins) ? v.pins.map(String) : [],
    otherCollapsed: !!v.otherCollapsed,
    compact: !!v.compact,
    flat: !!v.flat,
  };
  for (const c of initial.conversations) state.convs.set(c.key, c);

  sb.on('conversations', ({ provider, list }) => {
    for (const [key, c] of state.convs) if (c.provider === provider) state.convs.delete(key);
    for (const c of list) state.convs.set(c.key, c);
    if (state.openKey && !state.convs.has(state.openKey)) {
      state.openKey = null;
      showPane('empty');
    }
    scheduleRender();
  });
  sb.on('status', s => {
    state.statuses[s.provider] = s;
    renderStatus();
    if (!$('#settings').hidden) renderSettings();
  });
  sb.on('message', onMessage);
  sb.on('reaction', ({ key, messageId, reaction, mine, delta }) => applyReaction(key, messageId, reaction, mine, delta));
  sb.on('hotkey', hotkey); // pressed while a web app had focus

  bindUi();
  syncWebviews();
  renderStatus();
  renderSidebar();
  updateBadge();

  const s = state.settings;
  if (!s.demo && !s.hasDiscord && !s.hasMattermost && !s.slack.length) openSettings();
}

init();
