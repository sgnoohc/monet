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
  view: { mode: 'all', keys: new Set(), groups: [], assign: new Map(), nicknames: new Map(), people: new Map(), pins: [], otherCollapsed: false, compact: false, flat: false, bigPictures: true, dmNames: true, showTimes: true, tags: [], tagOf: new Map(), backgrounds: new Map() },
  editing: false,
  editTab: 'show', // Edit chooses which chats to 'show' or to 'pin'
  dragKey: null, // chat being dragged onto a group
  renaming: null, // group id whose name is being edited
  renamingConv: null, // chat key whose nickname is being edited
  renderPending: false,
  searchKey: null, // match that Enter opens while searching
  floatKey: null, // open chat that was unread when opened; stays on top until you leave it
  newMark: null, // { key, id } or { key, count }: where the "New" line goes in the open chat
  sync: null, // sync between Macs: status from the main process (Settings)
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

// h() leaves out empty children (null, false); replaceChildren and append do the
// same here, so a piece that isn't shown never turns up as the text "null".
for (const name of ['replaceChildren', 'append']) {
  const native = Element.prototype[name];
  Element.prototype[name] = function (...kids) {
    return native.apply(this, kids.filter(k => k != null && k !== false));
  };
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

// look: a person's chosen color/picture (see lookOf); tint puts the color on the picture too.
// base: the color when no picture or color was chosen (else one from the name).
// url may be "ref:<account>:<ref>": a picture that needs the login (Mattermost
// profile pictures); initials show until it has loaded.
const avatarUrls = new Map(); // ref -> blob: URL, once loaded
const avatarFailed = new Map(); // ref -> when it failed; not retried for a while
function avatarEl(name, url, cls = '', look = null, base = null) {
  const tint = look?.tint ? look.color : null;
  const fallback = () => h('div', { class: `avatar ${cls}`, style: `background:${tint || base || hashColor(name)}` }, initials(name));
  let src = look?.image || url;
  if (!src) return fallback();
  const img = () => {
    const el = h('img', { class: `avatar ${cls}`, src, alt: '', style: tint ? `box-shadow:0 0 0 2px ${tint}` : null });
    el.addEventListener('error', () => el.replaceWith(fallback()), { once: true });
    return el;
  };
  if (src.startsWith('ref:')) {
    const [, account, ref] = src.match(/^ref:([^:]+):(.+)$/) || [];
    if (!ref) return fallback();
    if (avatarUrls.has(ref)) {
      src = avatarUrls.get(ref);
      return img();
    }
    const placeholder = fallback();
    if (Date.now() - (avatarFailed.get(ref) || 0) < 5 * 60000) return placeholder;
    mediaUrl(`${account}:avatar`, ref).then(blobUrl => {
      avatarUrls.set(ref, blobUrl);
      src = blobUrl;
      if (placeholder.isConnected) placeholder.replaceWith(img());
    }, () => avatarFailed.set(ref, Date.now()));
    return placeholder;
  }
  return img();
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

// Bare links, and Markdown ones ("[notes](https://...)") showing just their text.
function linkify(text) {
  const out = [];
  const re = /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|https?:\/\/[^\s<>"')\]]+/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const url = m[2] || m[0];
    out.push(h('a', { href: '#', title: url, onclick: e => { e.preventDefault(); e.stopPropagation(); sb.openExternal(url); } }, m[1] || url));
    last = m.index + m[0].length;
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
    people: Object.fromEntries(v.people),
    pins: v.pins,
    otherCollapsed: v.otherCollapsed,
    compact: v.compact,
    flat: v.flat,
    bigPictures: v.bigPictures,
    dmNames: v.dmNames,
    showTimes: v.showTimes,
    tags: v.tags,
    tagOf: Object.fromEntries(v.tagOf),
    backgrounds: Object.fromEntries(v.backgrounds),
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

function setShowTimes(on) {
  state.view.showTimes = on;
  saveView();
  if (state.openKey && state.messages.has(state.openKey)) {
    const box = $('#messages');
    const top = box.scrollTop;
    renderMessages(state.openKey);
    if (stickToBottom) scrollToBottom();
    else box.scrollTop = top;
  }
}

function setDmNames(on) {
  state.view.dmNames = on;
  saveView();
  if (state.openKey && state.messages.has(state.openKey)) {
    const box = $('#messages');
    const top = box.scrollTop;
    renderMessages(state.openKey);
    if (stickToBottom) scrollToBottom();
    else box.scrollTop = top;
  }
}

function setBigPictures(on) {
  state.view.bigPictures = on;
  document.body.classList.toggle('big-pictures', on);
  saveView();
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
    {
      label: 'Tag',
      submenu: [
        ...state.view.tags.map(t => ({ id: `tag:${t.id}`, label: `${tagEmoji(t.color)}  ${t.name}`, checked: state.view.tagOf.get(c.key) === t.id })),
        ...(state.view.tags.length ? [{ type: 'separator' }] : []),
        { id: 'tag:new', label: 'New tag…' },
        ...(state.view.tagOf.has(c.key) ? [{ id: 'tag:', label: 'Remove tag' }] : []),
      ],
    },
    { type: 'separator' },
    { id: 'rename', label: 'Rename (only you see this)…' },
    ...(state.view.nicknames.has(c.key) ? [{ id: 'reset', label: `Reset name to "${c.title}"` }] : []),
    { id: 'look', label: c.peerId ? 'Tag, color and picture…' : 'Tag and picture…' },
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
  else if (choice === 'look') openLookDialog(c);
  else if (choice === 'tag:new') {
    openLookDialog(c);
    setTimeout(() => document.querySelector('.tag-new')?.focus(), 50);
  } else if (choice.startsWith('tag:')) {
    const id = choice.slice(4);
    setTag([c.key], id && state.view.tagOf.get(c.key) !== id ? id : null);
  }
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
  // Right away, not in the frame below: a hidden or minimized window draws no
  // frames, and that is exactly when the Dock count matters.
  updateBadge();
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    // Re-rendering mid-drag or mid-rename would destroy what the user is holding.
    if (state.dragKey || state.renaming || state.renamingConv || state.renamingTag) {
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
      if (state.filter.startsWith('tag:') && tagFor(c)?.id !== state.filter.slice(4)) return false;
      if (state.dmOnly && c.kind !== 'dm' && c.kind !== 'group') return false;
      if (q && !`${displayTitle(c)} ${c.title} ${c.subtitle}`.toLowerCase().includes(q)) return false;
      return true;
    })
    .sort((a, b) => (b.lastActivity || 0) - (a.lastActivity || 0));
}

function setDmOnly(on) {
  state.dmOnly = on;
  try {
    localStorage.setItem('dmOnly', on ? '1' : '');
  } catch {}
  renderSidebar();
}

function renderFilters() {
  const present = new Set([...state.convs.values()].map(c => c.service));
  const chips = [['all', 'All'], ['unread', 'Unread']];
  for (const s of ['discord', 'mattermost', 'slack']) if (present.has(s)) chips.push([s, SERVICES[s].name]);
  if (state.filter.startsWith('tag:') && !tagById(state.filter.slice(4))) state.filter = 'all';
  syncTagMenu();
  $('#filters').replaceChildren(
    ...chips.map(([id, label]) =>
      h('button', { class: `chip${state.filter === id ? ' on' : ''}`, onclick: () => { state.filter = id; renderSidebar(); } }, label)),
    // A toggle on top of the other filters: e.g. Unread + DMs, or a tag + DMs.
    h('button', {
      class: `chip dm-toggle${state.dmOnly ? ' on' : ''}`,
      title: state.dmOnly ? 'Showing only direct and group messages; click to show channels too' : 'Show only direct and group messages (no channels)',
      onclick: () => setDmOnly(!state.dmOnly),
    }, 'DMs'),
    ...state.view.tags.map(t => (state.renamingTag === t.id
      ? h('span', { class: 'chip tag-filter on', style: `--tag:${t.color}` }, h('span', { class: 'tag-dot' }),
        inlineInput('tag-rename', t.name, v => {
          state.renamingTag = null;
          if (v != null && v.trim()) updateTag(t.id, { name: v.trim().slice(0, 40) });
          renderSidebar();
        }))
      : h('button', {
        class: `chip tag-filter${state.filter === `tag:${t.id}` ? ' on' : ''}`,
        style: `--tag:${t.color}`,
        title: MOBILE ? 'Long-press to rename or recolor'
          : `${state.view.tags.indexOf(t) < 9 ? `⌘${state.view.tags.indexOf(t) + 1} · ` : ''}Right-click or double-click to rename or recolor`,
        onclick: () => { state.filter = state.filter === `tag:${t.id}` ? 'all' : `tag:${t.id}`; renderSidebar(); },
        ondblclick: MOBILE ? null : () => startRenameTag(t.id),
        oncontextmenu: e => {
          e.preventDefault();
          tagMenu(t);
        },
      }, h('span', { class: 'tag-dot' }), t.name))),
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
  h('div', { class: `conv-avatar${tagFor(c) ? ' tagged' : ''}`, style: tagFor(c) ? `--tag:${tagFor(c).color}` : null, title: tagFor(c)?.name || null },
    avatarEl(name, c.avatar, '', convLook(c), chatBase(c)),
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
  document.body.classList.toggle('big-pictures', state.view.bigPictures);
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
  const expandAll = state.editing || !!state.query.trim() || state.filter !== 'all' || state.dmOnly;

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
      state.query || state.filter !== 'all' || state.dmOnly ? 'Nothing matches'
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
let lastBadge = null;
function updateBadge() {
  let n = 0;
  for (const c of state.convs.values()) {
    if (c.muted) continue;
    n += isVisible(c) || c.kind !== 'channel' ? unreadOf(c) : c.mentions || 0;
  }
  for (const count of Object.values(state.appBadges)) n += count;
  if (n !== lastBadge) sb.setBadge(n);
  lastBadge = n;
}

// ---------- conversation pane ----------

function showPane(name) {
  for (const id of ['empty', 'chat', 'web']) $(`#${id}-pane`).hidden = id !== name;
}

function renderHeader(c) {
  const svc = SERVICES[c.service];
  // Filtered: replaceChildren would show a skipped (null) button as the text "null".
  $('#chat-header').replaceChildren(...[
    ...(MOBILE ? [h('button', { class: 'back-btn', 'aria-label': 'Back', onclick: closeConversation }, '‹')] : []),
    h('button', {
      class: `person-btn${tagFor(c) ? ' tagged' : ''}`,
      style: tagFor(c) ? `--tag:${tagFor(c).color}` : null,
      title: `${tagFor(c) ? `Tag: ${tagFor(c).name}. ` : ''}Tag this chat, or choose a ${c.peerId ? 'color or picture for this person' : 'picture for it'}`,
      onclick: () => openLookDialog(c),
    }, avatarEl(displayTitle(c), c.avatar, '', convLook(c), chatBase(c))),
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
      c.topic
        ? h('div', { class: 'chat-sub chat-topic', title: 'Channel header and pinned messages', onclick: () => openChannelInfo(c) }, ...linkify(c.topic.replace(/\s*\n\s*/g, ' · ')))
        : h('div', { class: 'chat-sub' }, displayTitle(c) !== c.title ? `${c.title} · ${c.subtitle}` : c.subtitle)),
    c.hasMembers ? membersButton(c) : null,
    c.hasPins ? pinButton(c) : null,
    h('span', { class: `svc-tag svc-${c.service}` }, svc?.name || c.service),
  ].filter(Boolean));
  $('#composer-input').placeholder = `Message ${displayTitle(c)}`;
}

// Pinned messages, fetched when a chat opens and kept for a couple of minutes.
const pinCache = new Map(); // key -> { at, list: Promise<message[]> }
function pinsOf(key, fresh = false) {
  const hit = pinCache.get(key);
  if (hit && !fresh && Date.now() - hit.at < 120000) return hit.list;
  const list = sb.pinned(key).catch(() => []);
  pinCache.set(key, { at: Date.now(), list });
  return list;
}

// Who is in a channel, fetched when it opens and kept for a few minutes.
const memberCache = new Map(); // key -> { at, list: Promise<{ total, people }> }
function membersOf(key, fresh = false) {
  const hit = memberCache.get(key);
  if (hit && !fresh && Date.now() - hit.at < 300000) return hit.list;
  const list = sb.members(key);
  list.catch(() => memberCache.delete(key));
  memberCache.set(key, { at: Date.now(), list });
  return list;
}

// "👥 27" in the header; opens the info panel at the member list.
function membersButton(c) {
  const btn = h('button', { class: 'pin-btn', hidden: true, title: 'Who is in this chat', onclick: () => openChannelInfo(c, 'members') });
  membersOf(c.key).then(m => {
    btn.textContent = `👥 ${m.total}`;
    btn.hidden = false;
  }, () => {});
  return btn;
}

// Members in the info panel; a filter box when there are many. Tapping someone
// opens your direct message with them when you have one, else their color and picture.
function memberSection(c, close) {
  const list = h('div', { class: 'member-list' }, h('p', {}, 'Loading…'));
  const heading = h('h3', {}, 'Members');
  const section = h('section', { class: 'members-section' }, heading, list);
  membersOf(c.key, true).then(({ total, people }) => {
    const sorted = [...people].sort((a, b) => (b.isSelf - a.isSelf) || a.name.localeCompare(b.name));
    heading.textContent = `Members (${total})`;
    const rows = query => sorted
      .filter(p => !query || `${p.name} ${p.username}`.toLowerCase().includes(query))
      .map(p => {
        const dm = [...state.convs.values()].find(x => x.provider === c.provider && x.peerId === p.id);
        return h('button', {
          class: 'member',
          title: p.isSelf ? '' : dm ? `Open your chat with ${p.name}` : `Color or picture for ${p.name}`,
          onclick: () => {
            if (p.isSelf) return;
            close();
            if (dm) openConversation(dm.key);
            else openPersonDialog(c.key, { id: p.id, name: p.name, avatar: p.avatar });
          },
        },
        avatarEl(p.name, p.avatar, 'member-avatar', lookOf(personKey(c.key, p))),
        h('span', { class: 'member-name' }, p.isSelf ? `${p.name} (you)` : p.name),
        p.username ? h('span', { class: 'member-user' }, `@${p.username}`) : null);
      });
    const more = total > people.length ? h('p', {}, `…and ${total - people.length} more`) : null;
    const box = h('div', {});
    const show = query => box.replaceChildren(...rows(query), ...(query ? [] : [more].filter(Boolean)));
    const filter = people.length > 12
      ? h('input', { class: 'member-filter', type: 'search', placeholder: 'Find a member', oninput: e => show(e.target.value.trim().toLowerCase()) })
      : null;
    show('');
    list.replaceChildren(...[filter, box].filter(Boolean));
  }, e => list.replaceChildren(h('p', {}, cleanError(e))));
  return section;
}

// "📌 3" in the header when the chat has pinned messages; opens the info panel.
function pinButton(c) {
  const btn = h('button', { class: 'pin-btn', hidden: true, title: 'Pinned messages', onclick: () => openChannelInfo(c) });
  pinsOf(c.key).then(list => {
    btn.textContent = `📌 ${list.length}`;
    btn.hidden = !list.length;
  });
  return btn;
}

// The channel header in full, the pinned messages (newest first; tapping one
// jumps to it in the chat), then who is in it. focus 'members' scrolls there.
function openChannelInfo(c, focus = null) {
  const modal = h('div', { class: 'modal', onclick: e => e.target === modal && close() });
  const onKey = e => {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    close();
  };
  const close = () => {
    modal.remove();
    document.removeEventListener('keydown', onKey, true);
    if (closeChannelInfo === close) closeChannelInfo = null;
  };
  closeChannelInfo = close;
  const list = h('div', { class: 'pin-list' }, h('p', {}, 'Loading…'));
  modal.append(h('div', { class: 'dialog info-dialog' },
    h('h2', {}, displayTitle(c)),
    c.topic ? h('section', {}, h('h3', {}, 'Header'), h('div', { class: 'info-topic' }, ...richText(c.topic))) : null,
    c.hasPins ? h('section', {}, h('h3', {}, 'Pinned messages'), list) : null,
    c.hasMembers ? memberSection(c, () => close()) : null,
    h('div', { class: 'row end' }, h('button', { class: 'btn', onclick: () => close() }, 'Close'))));
  document.addEventListener('keydown', onKey, true);
  document.body.append(modal);
  if (focus === 'members') modal.querySelector('.members-section')?.scrollIntoView({ block: 'start' });
  pinsOf(c.key, true).then(pins => {
    if (!pins.length) return list.replaceChildren(h('p', {}, 'Nothing is pinned in this chat.'));
    list.replaceChildren(...pins.map(m => h('div', {
      class: 'pin-item',
      onclick: e => {
        if (e.target.closest('a, img, video, .file-chip')) return;
        close();
        jumpToMessage(m.id, m.ts);
      },
    },
      h('div', { class: 'pin-meta' }, h('b', {}, m.isSelf ? 'You' : m.author.name), ` · ${formatDay(m.ts)} ${formatTime(m.ts)}`),
      m.text ? h('div', { class: 'pin-text' }, ...richText(m.text, m.customEmoji)) : null,
      ...(m.attachments || []).map(mediaEl))));
  });
}
let closeChannelInfo = null;

async function openConversation(key) {
  const conv = state.convs.get(key);
  if (!conv) return;
  closePopover?.();
  state.openKey = key;
  state.openApp = null;
  showWebview(null);
  closeGifPanel();
  showPane('chat');
  document.body.classList.add('chat-open');
  renderHeader(conv);
  applyChatBackground();
  renderStaged();
  if (state.share) deliverShare();
  state.floatKey = !conv.muted && (conv.unread || conv.mentions) ? key : null;
  state.newMark = unreadOf(conv) > 0 ? { key, count: unreadOf(conv) } : null;
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
    const mark = state.newMark;
    if (mark?.key === key && !mark.id) {
      // Fixed now that the latest messages are in, so later arrivals don't move it.
      const list = state.messages.get(key);
      mark.id = list[Math.max(0, list.length - mark.count)]?.id;
    }
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

const signature = list => JSON.stringify((list || []).map(m => [m.id, m.text, m.replyTo?.id, m.reactions?.map(r => [r.key, r.count, r.me])]));

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

// ```code blocks``` (an optional language word on the opening line is dropped)
// and `inline code`, shown in monospace with no links or emoji inside.
const CODE_RE = /```(?:[\w+#.-]*\n)?([\s\S]*?)```|`([^`\n]+)`/g;

// Text with code, links, plus custom emoji (":name:" with an image in customEmoji).
function richText(text, customEmoji = {}) {
  const out = [];
  let last = 0;
  let m;
  CODE_RE.lastIndex = 0;
  while ((m = CODE_RE.exec(text))) {
    const block = m[2] == null;
    // A block sits on its own lines, so the line breaks around it would only add gaps.
    let before = text.slice(last, m.index);
    if (block) before = before.replace(/\n$/, '');
    if (before) out.push(...plainRichText(before, customEmoji));
    out.push(block
      ? h('pre', { class: 'code-block' }, m[1].replace(/^\n/, '').replace(/\n$/, ''))
      : h('code', { class: 'code-inline' }, m[2]));
    last = m.index + m[0].length;
    if (block && text[last] === '\n') last++;
  }
  if (last < text.length) out.push(...plainRichText(text.slice(last), customEmoji));
  return out;
}

function plainRichText(text, customEmoji) {
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
// phone it is downloaded and handed to the phone's own viewer (PDF viewer,
// video player, ...).
async function openAttachment(a) {
  const key = state.openKey;
  toast(MOBILE ? `Opening ${a.name}…` : `Downloading ${a.name}…`);
  try {
    const saved = await sb.openFile(key, a);
    if (!MOBILE) toast(`Saved to Downloads: ${saved.split('/').pop()}`);
  } catch (e) {
    toast(cleanError(e));
  }
}

// Shows the bubble's picture at once, then swaps in the full-size file when
// the bubble only had a preview.
function showLightbox(src, a) {
  const key = state.openKey;
  // Esc closes the picture, and only the picture: a thread or panel it was opened from stays.
  const onKey = e => {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    e.stopImmediatePropagation();
    close();
  };
  const close = () => {
    box.remove();
    window.removeEventListener('keydown', onKey, true);
  };
  window.addEventListener('keydown', onKey, true);
  const img = h('img', { src, alt: a.name, onclick: e => e.stopPropagation() });
  const box = h('div', { class: 'lightbox', onclick: close },
    img,
    h('div', { class: 'lightbox-bar', onclick: e => e.stopPropagation() },
      h('span', { class: 'lightbox-name' }, a.name, a.size ? ` · ${formatSize(a.size)}` : ''),
      h('button', { class: 'btn small', onclick: () => openAttachment(a) }, MOBILE ? 'Open' : 'Save to Downloads'),
      h('button', { class: 'btn small', onclick: close }, 'Close')));
  document.body.append(box);
  if (a.ref && a.thumbRef && a.thumbRef !== a.ref) {
    mediaUrl(key, a.ref).then(url => { img.src = url; }).catch(() => {});
  }
}

const fileIcon = name => (/\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(name) ? '🎬'
  : /\.(mp3|m4a|wav|aac|ogg|flac|opus)$/i.test(name) ? '🎵' : '📄');

function fileChip(a) {
  return h('a', {
    class: 'bubble file',
    href: '#',
    title: MOBILE ? null : 'Save to Downloads and open',
    onclick: e => { e.preventDefault(); openAttachment(a); },
  },
  h('span', { class: 'file-icon' }, fileIcon(a.name)),
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

// A file waiting to be sent: a preview, its name and size, and ✕ to drop it.
function stagedFileEl(f, remove) {
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
    h('button', { class: 'staged-remove', title: 'Remove', 'aria-label': 'Remove', onclick: remove }, '✕'));
}

// Files as the upload call wants them; pasted images get a name.
const filePayload = files => Promise.all(files.map(async (f, i) => ({
  name: f.name || `pasted-${Date.now()}-${i}.${(f.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`,
  type: f.type,
  data: new Uint8Array(await f.arrayBuffer()),
})));

function renderStaged() {
  const key = state.openKey;
  const files = stagedFiles.get(key) || [];
  const tray = $('#staged');
  tray.hidden = !files.length;
  tray.replaceChildren(
    ...files.map(f => stagedFileEl(f, () => unstage(key, f))),
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
    const payload = await filePayload(files);
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

function reactionChips(m, convKey) {
  if (!m.reactions?.length) return null;
  return h('div', { class: 'reactions' }, ...m.reactions.map(r => h('button', {
    class: `reaction${r.me ? ' mine' : ''}`,
    onclick: e => {
      e.stopPropagation();
      hideReactTip();
      react(m, r.key, !r.me);
    },
    // Hover (or long-press on the phone) shows who reacted.
    onmouseenter: MOBILE ? null : e => {
      const chip = e.currentTarget;
      clearTimeout(tipTimer);
      tipTimer = setTimeout(() => showReactTip(convKey, m, r, chip), 250);
    },
    onmouseleave: MOBILE ? null : hideReactTip,
    oncontextmenu: e => {
      e.preventDefault();
      e.stopPropagation();
      showReactTip(convKey, m, r, e.currentTarget);
    },
  },
  r.imageUrl ? h('img', { src: r.imageUrl, alt: r.name }) : (r.emoji || `:${r.name}:`),
  h('span', {}, r.count))));
}

// quote: show the faded original above a reply (off in the thread view, and for
// a run of replies to the same message). replies: how many replies this one has.
function bubbleEl(m, { key, last, showName, showAvatar, quote = true, replies = 0 }) {
  const look = showName || showAvatar ? lookOf(personKey(key, m.author)) : null;
  const parts = [];
  if (m.text) {
    const emoji = isEmojiOnly(m.text, m.customEmoji);
    parts.push(h('div', { class: `bubble${emoji ? ' emoji' : ''}${m.mentionsMe && !m.isSelf ? ' mention' : ''}` }, ...richText(m.text, m.customEmoji)));
  }
  for (const a of m.attachments || []) parts.push(mediaEl(a));
  if (last && parts.length) parts[parts.length - 1].classList.add('tail');
  const author = showName ? h('span', {
    class: 'msg-author',
    style: look?.color ? `color:${look.color}` : null,
    title: 'Choose a color or picture for this person',
    onclick: e => { e.stopPropagation(); openPersonDialog(key, m.author); },
  }, m.author.name) : null;
  const label = author || m.isReply ? [author, author && m.isReply ? ' · ' : null, m.isReply ? 'reply in thread' : null] : null;
  if (m.replyTo && quote) {
    // Like iMessage: a faded copy of the original above the reply, joined to it
    // by a thin curved line; tapping it opens the thread.
    parts.unshift(h('div', {
      class: 'reply-ghost',
      title: m.replyTo.id ? `Reply to ${m.replyTo.author || 'a message'}: open the thread` : null,
      onclick: () => m.replyTo.id && openThread(key, threadRootOf(m)),
    },
    h('div', { class: 'reply-ghost-bubble' },
      m.replyTo.author ? h('span', { class: 'reply-ghost-author' }, `${m.replyTo.author}: `) : null,
      (m.replyTo.text || '').replace(/\s+/g, ' ').trim() || 'Message')));
  }
  if (replies > 0) {
    parts.push(h('button', { class: 'reply-count', onclick: () => openThread(key, m.id) }, `${replies} ${replies === 1 ? 'Reply' : 'Replies'}`));
  }
  const stack = h('div', {
    class: 'msg-stack',
    // A double-tap while scrolling would open it by accident on the phone, so there it's long-press only.
    ondblclick: MOBILE ? null : e => {
      window.getSelection()?.removeAllRanges();
      openReactionPicker(m, e.currentTarget);
    },
    oncontextmenu: e => {
      e.preventDefault();
      openReactionPicker(m, e.currentTarget, MOBILE ? { x: e.clientX, y: e.clientY } : null);
    },
  },
  label ? h('div', { class: 'msg-name' }, label) : null,
  ...parts,
  reactionChips(m, key),
  // When it was sent, under the last message of each run (hover any message for its own time).
  last && state.view.showTimes ? h('div', { class: 'msg-time' }, formatTime(m.ts)) : null);
  const reactBtn = MOBILE ? null : h('button', {
    class: 'react-btn',
    title: 'React',
    onclick: e => { e.stopPropagation(); openReactionPicker(m, stack); },
  }, '☺︎');
  return h('div', {
    class: `msg-row ${m.isSelf ? 'me' : 'them'}${last ? ' last' : ''}`,
    'data-id': m.id,
    title: formatTime(m.ts),
    onclick: e => {
      if (showAvatar && e.target.closest('.msg-avatar')) openPersonDialog(key, m.author);
    },
  },
    showAvatar ? (last ? avatarEl(m.author.name, m.author.avatar, 'msg-avatar', look) : h('div', { class: 'msg-avatar' })) : null,
    m.isSelf ? reactBtn : null,
    stack,
    m.isSelf ? null : reactBtn);
}

// ----- reactions -----

const QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🙏'];

let closePopover = null; // closes whichever reaction picker or "who reacted" tip is open

// Shows el until a touch or click lands outside it, the chat scrolls, or
// Back is pressed. The press is caught on its way down, so handlers that stop
// clicks from bubbling can't leave it stuck on screen.
function showPopover(el) {
  closePopover?.();
  const outside = e => {
    if (!el.contains(e.target)) close();
  };
  const close = () => {
    el.remove();
    document.removeEventListener('pointerdown', outside, true);
    $('#messages').removeEventListener('scroll', onScroll);
    if (closePopover === close) closePopover = null;
  };
  document.body.append(el);
  document.addEventListener('pointerdown', outside, true);
  const onScroll = () => userScrolling() && close();
  $('#messages').addEventListener('scroll', onScroll, { passive: true });
  closePopover = close;
  return close;
}

function closePicker() {
  if (document.querySelector('.react-picker')) closePopover?.();
}

// point: where a long-press landed; the picker goes just above it. Either
// way it stays inside the chat pane, never pinned to the top of the screen.
function openReactionPicker(m, anchor, point = null) {
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
    state.openKey && !m.system ? h('button', { class: 'copy', onclick: () => { closePicker(); openThread(state.openKey, threadRootOf(m), { reply: true }); } }, 'Reply') : null,
    m.text ? h('button', { class: 'copy', onclick: () => { sb.copyText(m.text); closePicker(); toast('Copied'); } }, 'Copy') : null);
  showPopover(picker);
  const box = anchor.getBoundingClientRect();
  const pane = $('#messages').getBoundingClientRect();
  const width = picker.offsetWidth;
  const height = picker.offsetHeight;
  const minTop = pane.top + 6;
  const maxTop = Math.max(minTop, pane.bottom - height - 6);
  let top;
  if (point) top = point.y - height - 16 >= minTop ? point.y - height - 16 : point.y + 16;
  else if (box.top - height - 6 >= minTop) top = box.top - height - 6;
  else if (box.bottom + 6 <= maxTop) top = box.bottom + 6;
  else top = minTop; // a bubble taller than the pane
  picker.style.top = `${Math.min(maxTop, Math.max(minTop, top))}px`;
  const left = point ? point.x - width / 2 : m.isSelf ? box.right - width : box.left;
  picker.style.left = `${Math.min(window.innerWidth - width - 8, Math.max(8, left))}px`;
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

// ----- who reacted -----

// Names per message/emoji/count, so hovering again doesn't ask the server again.
const reactorCache = new Map();
let tipTimer;

function hideReactTip() {
  clearTimeout(tipTimer);
  if (document.querySelector('.react-tip')) closePopover?.();
}

function reactorText(names, r) {
  const list = [...names.filter(n => n === 'You'), ...names.filter(n => n !== 'You')];
  const shown = list.slice(0, 12);
  const others = Math.max(r.count, list.length) - shown.length;
  const parts = others ? [...shown, `${others} other${others === 1 ? '' : 's'}`] : shown;
  if (!parts.length) return 'No one yet';
  const joined = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
  return r.emoji ? `${joined} reacted` : `${joined} reacted with :${r.name}:`;
}

function showReactTip(convKey, m, r, anchor) {
  hideReactTip();
  const text = h('div', { class: 'react-tip-text' }, 'Loading…');
  const tip = h('div', { class: 'react-tip' },
    h('div', { class: 'react-tip-emoji' }, r.imageUrl ? h('img', { src: r.imageUrl, alt: r.name }) : r.emoji || `:${r.name}:`),
    text);
  showPopover(tip);
  const place = () => {
    const box = anchor.getBoundingClientRect();
    const left = box.left + box.width / 2 - tip.offsetWidth / 2;
    tip.style.left = `${Math.min(window.innerWidth - tip.offsetWidth - 8, Math.max(8, left))}px`;
    const above = box.top - tip.offsetHeight - 6;
    tip.style.top = `${above >= 8 ? above : box.bottom + 6}px`;
  };
  place();
  const id = [convKey, m.id, r.key, r.count, r.me].join('|');
  if (!reactorCache.has(id)) {
    reactorCache.set(id, sb.reactors(convKey, m.id, r.key).catch(e => {
      reactorCache.delete(id);
      throw e;
    }));
  }
  reactorCache.get(id).then(
    names => { text.textContent = reactorText(names, r); },
    e => { text.textContent = cleanError(e); },
  ).finally(() => tip.isConnected && place());
}

// ----- people -----

// A person's color and picture, chosen by you and keyed by account + user id.
const PERSON_COLORS = ['#e5484d', '#f76b15', '#c99400', '#30a46c', '#12a594', '#0090ff', '#3e63dd', '#8e4ec6', '#d6409f', '#8d8d86'];
const personKey = (convKey, author) => `${state.convs.get(convKey)?.provider || convKey.split(':')[0]}:${author.id}`;
const lookOf = pkey => state.view.people.get(pkey) || null;
// A direct message uses the person's look; a group or channel has its own.
const chatLookKey = c => `chat:${c.key}`;
const convLook = c => (c.peerId ? lookOf(`${c.provider}:${c.peerId}`) : { image: lookOf(chatLookKey(c))?.image });
// Groups and channels are gray unless tagged; people keep a color from their name.
const CHAT_GRAY = '#7a7a80';
const chatBase = c => (c.peerId ? null : tagFor(c)?.color || CHAT_GRAY);

// ----- color tags: named colors on any chat, or on a whole server (Mattermost
// team, Discord server, Slack workspace). A chat's own tag wins over its
// server's. Tagged chats get a ring in the tag's color, and each tag is a
// filter above the list. -----

const COLOR_NAMES = { '#e5484d': 'Red', '#f76b15': 'Orange', '#c99400': 'Yellow', '#30a46c': 'Green', '#12a594': 'Teal', '#0090ff': 'Blue', '#3e63dd': 'Indigo', '#8e4ec6': 'Purple', '#d6409f': 'Pink', '#8d8d86': 'Gray' };
const serverTagKey = c => (c.server ? `server:${c.provider}:${c.server.id}` : null);
const tagById = id => (id && state.view.tags.find(t => t.id === id)) || null;
const tagFor = c => tagById(state.view.tagOf.get(c.key)) || (c.server ? tagById(state.view.tagOf.get(serverTagKey(c))) : null);

function setTag(keys, id) {
  for (const key of keys) {
    if (id) state.view.tagOf.set(key, id);
    else state.view.tagOf.delete(key);
  }
  saveView();
  scheduleRender();
  const open = state.convs.get(state.openKey);
  if (open) renderHeader(open);
}

function createTag(name) {
  const used = new Set(state.view.tags.map(t => t.color));
  const color = PERSON_COLORS.find(c => !used.has(c)) || PERSON_COLORS[state.view.tags.length % PERSON_COLORS.length];
  const tag = { id: `t${Date.now().toString(36)}`, name: name.trim().slice(0, 40) || 'Tag', color };
  state.view.tags.push(tag);
  saveView();
  renderFilters();
  return tag;
}

function updateTag(id, changes) {
  Object.assign(tagById(id) || {}, changes);
  saveView();
  scheduleRender();
  const open = state.convs.get(state.openKey);
  if (open) renderHeader(open);
}

function moveTag(i, delta) {
  const list = state.view.tags;
  const j = i + delta;
  if (j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
  saveView();
  scheduleRender();
}

// ⌘1–⌘9: just the chats with that tag; the same key again shows everything.
function showTag(n) {
  const tag = state.view.tags[n - 1];
  if (!tag) return toast(`There is no tag ${n} yet`);
  state.filter = state.filter === `tag:${tag.id}` ? 'all' : `tag:${tag.id}`;
  renderSidebar();
}

let menuTags = '';
function syncTagMenu() {
  const names = JSON.stringify(state.view.tags.map(t => t.name));
  if (names === menuTags || !sb.setTagNames) return;
  menuTags = names;
  sb.setTagNames(state.view.tags.map(t => t.name));
}

function startRenameTag(id) {
  state.renamingTag = id;
  renderSidebar();
}

async function tagMenu(t) {
  const count = [...state.convs.values()].filter(c => tagFor(c)?.id === t.id).length;
  const choice = await sb.popupMenu([
    { id: 'rename', label: 'Rename…' },
    {
      label: 'Color',
      submenu: PERSON_COLORS.map(color => ({ id: `color:${color}`, label: `${tagEmoji(color)}  ${COLOR_NAMES[color]}`, checked: t.color === color })),
    },
    { type: 'separator' },
    { id: 'delete', label: `Delete "${t.name}" (${count} chat${count === 1 ? '' : 's'} untagged)` },
  ]);
  if (choice === 'rename') startRenameTag(t.id);
  else if (choice?.startsWith('color:')) updateTag(t.id, { color: choice.slice(6) });
  else if (choice === 'delete') deleteTag(t.id);
}

function deleteTag(id) {
  state.view.tags = state.view.tags.filter(t => t.id !== id);
  for (const [key, tid] of state.view.tagOf) if (tid === id) state.view.tagOf.delete(key);
  if (state.filter === `tag:${id}`) state.filter = 'all';
  saveView();
  scheduleRender();
  const open = state.convs.get(state.openKey);
  if (open) renderHeader(open);
}

// For menus, which can't show colors: the nearest colored circle.
function tagEmoji(color) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(color.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  if (max - min < 0.12) return max > 0.8 ? '⚪' : max < 0.25 ? '⚫' : '⚪';
  let hue = max === r ? ((g - b) / (max - min)) % 6 : max === g ? (b - r) / (max - min) + 2 : (r - g) / (max - min) + 4;
  hue = (hue * 60 + 360) % 360;
  return hue < 15 || hue >= 330 ? '🔴' : hue < 40 ? '🟠' : hue < 70 ? '🟡' : hue < 170 ? '🟢' : hue < 265 ? '🔵' : '🟣';
}

// Colors put on single chats before tags existed become tags named after the color.
function migrateChatColors() {
  if (state.view.tags.length) return;
  const byColor = new Map();
  for (const [key, look] of state.view.people) {
    if (!key.startsWith('chat:') || !look.color) continue;
    if (!byColor.has(look.color)) byColor.set(look.color, []);
    byColor.get(look.color).push(key.slice(5));
    const { color, tint, ...rest } = look;
    if (rest.image) state.view.people.set(key, rest);
    else state.view.people.delete(key);
  }
  if (!byColor.size) return;
  for (const [color, keys] of byColor) {
    const tag = { id: `t-${color.slice(1).toLowerCase()}`, name: COLOR_NAMES[color.toLowerCase()] || color, color };
    state.view.tags.push(tag);
    for (const key of keys) state.view.tagOf.set(key, tag.id);
  }
  saveView();
}

// The tag chips in a chat's dialog: its own tag, and for a channel its server's.
function tagSection(conv, rerender) {
  const chips = (key, current) => state.view.tags.map(t => h('button', {
    class: `tag-chip${current === t.id ? ' on' : ''}`,
    style: `--tag:${t.color}`,
    onclick: () => {
      setTag([key], current === t.id ? null : t.id);
      rerender();
    },
  }, h('span', { class: 'tag-dot' }), t.name));
  const add = h('input', {
    class: 'tag-new',
    placeholder: '+ New tag',
    maxlength: '40',
    onkeydown: e => {
      if (e.key !== 'Enter' || !add.value.trim()) return;
      e.preventDefault();
      setTag([conv.key], createTag(add.value).id);
      rerender();
    },
  });
  const serverKey = serverTagKey(conv);
  return h('section', {},
    h('h3', {}, 'Tag'),
    h('p', {}, 'Rings this chat in the tag\'s color; each tag is also a filter above the chat list.'),
    h('div', { class: 'tag-chips' }, ...chips(conv.key, state.view.tagOf.get(conv.key)), add),
    serverKey && state.view.tags.length ? h('p', {}, `Or tag everything in ${conv.server.name}:`) : null,
    serverKey && state.view.tags.length ? h('div', { class: 'tag-chips' }, ...chips(serverKey, state.view.tagOf.get(serverKey))) : null);
}

// Color and picture for a chat: the person's for a direct message, else the chat's.
function openLookDialog(c) {
  if (c.peerId) openPersonDialog(c.key, { id: c.peerId, name: c.title, avatar: c.avatar }, null, c);
  else openPersonDialog(c.key, { name: displayTitle(c), avatar: c.avatar }, c, c);
}

function setLook(pkey, changes) {
  const next = { ...lookOf(pkey), ...changes };
  for (const k of Object.keys(next)) if (next[k] == null) delete next[k];
  if (!next.color) delete next.tint;
  if (next.color || next.image) state.view.people.set(pkey, next);
  else state.view.people.delete(pkey);
  saveView();
  scheduleRender();
  if (state.openKey && state.messages.has(state.openKey)) {
    const box = $('#messages');
    const top = box.scrollTop;
    renderMessages(state.openKey);
    box.scrollTop = top;
  }
}

// A square crop, small enough to keep in the settings file.
// ----- chat backgrounds, like iMessage: a gradient or your own picture behind
// a chat. A chat without one uses the background for all chats ("*"). -----

const BACKGROUNDS = [
  { id: 'sky', name: 'Sky' },
  { id: 'mint', name: 'Mint' },
  { id: 'sunset', name: 'Sunset' },
  { id: 'lavender', name: 'Lavender' },
  { id: 'sand', name: 'Sand' },
  { id: 'aurora', name: 'Aurora' },
  { id: 'night', name: 'Night' },
];

// What a chat shows: its own choice, else the one for all chats. { preset } / { image } / null
function backgroundOf(key) {
  const own = state.view.backgrounds.get(key);
  if (own) return own.preset === 'none' ? null : own;
  return state.view.backgrounds.get('*') || null;
}

let shownPhotoUrl = null;
function applyChatBackground() {
  const pane = $('#chat-pane');
  const bg = state.openKey ? backgroundOf(state.openKey) : null;
  pane.classList.toggle('has-bg', !!bg);
  for (const b of BACKGROUNDS) pane.classList.toggle(`bg-${b.id}`, bg?.preset === b.id);
  pane.classList.toggle('bg-image', !!(bg?.image || bg?.photo));
  if (!bg?.photo) {
    shownPhotoUrl = null;
    pane.style.setProperty('--chat-bg-image', bg?.image ? `url("${bg.image}")` : 'none');
    return;
  }
  const url = photoBgUrl(bg.photo);
  if (url === shownPhotoUrl) return;
  shownPhotoUrl = url;
  // Loaded first, then swapped in, so the old picture stays until the new one is ready.
  const img = new Image();
  img.onload = () => {
    if (shownPhotoUrl === url) pane.style.setProperty('--chat-bg-image', `url("${url}")`);
  };
  img.src = url;
}

// A bigger window wants a bigger picture (the size steps keep this rare).
let bgResizeTimer;
new ResizeObserver(() => {
  clearTimeout(bgResizeTimer);
  bgResizeTimer = setTimeout(() => {
    if (state.openKey && backgroundOf(state.openKey)?.photo) applyChatBackground();
  }, 300);
}).observe(document.getElementById('chat-pane'));

function setBackground(key, bg) {
  if (bg) state.view.backgrounds.set(key, bg);
  else state.view.backgrounds.delete(key);
  saveView();
  applyChatBackground();
}

// Free photos from Unsplash, served by picsum.photos: [id, photographer, width,
// height of the original]. All are large (about 5000 px), chosen to look good
// both whole (a wide window) and cut down the middle (the phone). Only the photo's
// number is saved; the picture is fetched at exactly the size of the chat on this
// screen, cut from the original, so it is sharp everywhere and nothing big is stored.
const WEB_PHOTOS = [
  ['1022', "Vashishtha Jogi", 5000, 2813],
  ['1002', "NASA", 4312, 2868],
  ['1041', "Tim Marshall", 5000, 2813],
  ['994', "Jonathan Bean", 5000, 3337],
  ['987', "Sebastien Gabriel", 5000, 3333],
  ['184', "Tim de Groot", 4288, 2848],
  ['213', "Kelly Sikkema", 4928, 3264],
  ['385', "Griffin Keller", 5000, 3333],
  ['1019', "Patrick Fore", 5000, 3333],
  ['412', "Samuel Rohl", 5000, 3337],
  ['110', "Kenneth Thewissen", 5000, 3333],
  ['1015', "Alexey Topolyanskiy", 5000, 3333],
  ['1036', "Wolfgang Lutz", 4608, 3072],
  ['327', "Ryan Schroeder", 4442, 2961],
  ['381', "Nick West", 5000, 3419],
  ['218', "Monika Majkowska", 4752, 3168],
  ['1043', "Christian Joudrey", 5000, 3333],
  ['989', "Paul Jarvis", 4896, 3264],
  ['990', "Joseph Barrientos", 5000, 3334],
  ['1039', "Andrew Coelho", 5000, 3337],
  ['1051', "Ales Krivec", 4928, 3264],
  ['1057', "Stefan Kunze", 5000, 3338],
  ['223', "Maria Carrasco", 4912, 3264],
  ['235', "Paul E. Harrer", 5000, 3333],
  ['251', "Tiago Gerken", 5000, 3333],
  ['279', "Taylor Leopold", 5000, 3333],
  ['350', "Forrest Cavale", 5000, 3338],
  ['368', "Tyssul Patel", 4896, 3264],
  ['377', "Martin Stan\u011bk", 4884, 3256],
  ['384', "Griffin Keller", 5000, 3333],
  ['392', "Chris Brignola", 5000, 3333],
  ['423', "Gabriel Santiago", 5000, 3333],
  ['432', "Michael Hull", 5000, 3333],
  ['465', "Paula Vermeulen", 4928, 3264],
  ['472', "Dustin Scarpitti", 5000, 3333],
  ['476', "Mr. Marco", 5000, 3333],
  ['477', "Jasper van der Meij", 4919, 3258],
  ['482', "Danny Froese", 5000, 3333],
  ['499', "Gabriel Santiago", 5000, 3333],
  ['509', "Jeff Sheldon", 4608, 3456],
  ['525', "Luca Zanon", 5000, 3333],
  ['543', "Ali Inay", 5000, 3333],
  ['558', "Ales Krivec", 4928, 3264],
  ['666', "Jason Ortego", 5000, 3333],
  ['676', "Drew Patrick Miller", 5000, 3324],
  ['705', "Breno Machado", 5000, 3333],
  ['723', "Blair Fraser", 5000, 3333],
  ['724', "Nelly Volkovich", 5000, 3333],
  ['730', "Ryan Pohanic", 5000, 3333],
  ['733', "Dominik Schr\u00f6der", 5000, 3334],
  ['765', "Grant McIver", 4586, 3439],
  ['774', "Alex Wigan", 5000, 3333],
  ['779', "John Kutcher", 4844, 3219],
  ['787', "Sebastien Gabriel", 5000, 3333],
  ['794', "Lauren Coleman", 5000, 3333],
  ['809', "Namphuong Van", 5000, 3333],
  ['813', "Roger Burkhard", 4896, 3264],
  ['814', "Ales Krivec", 5000, 3272],
  ['825', "Michael Hull", 5000, 3333],
  ['830', "Luca Zanon", 5000, 3333],
  ['831', "Luke Pamer", 5000, 3333],
  ['848', "Stefanus Martanto Setyo Husodo", 4912, 3264],
  ['857', "Dmitry Sytnik", 5000, 3088],
  ['866', "Samuel Zeller", 4704, 3136],
  ['871', "Stefan Kunze", 5000, 3338],
  ['872', "Brandon Lam", 4608, 3072],
  ['877', "Sebastian Unrau", 5000, 3014],
  ['894', "Paula Porto", 5000, 3333],
  ['896', "Jenna Beekhuis", 5000, 3333],
  ['905', "Caitlin Wynne", 5000, 3333],
  ['907', "Pierre Bouillot", 5000, 3259],
  ['912', "Clem Onojeghuo", 5000, 3333],
  ['913', "Mikkel Schmidt", 4522, 3015],
  ['925', "Patrick Fore", 5000, 3333],
  ['929', "Tiago Muraro", 5000, 3333],
  ['933', "Gian-Reto Tarnutzer", 4943, 3307],
  ['950', "Nitish Kadam", 5000, 3333],
  ['967', "NASA", 4928, 3280],
  ['973', "Cameron Kirby", 5000, 3334],
  ['980', "Ales Krivec", 5000, 3509],
  ['985', "Hide Obara", 5000, 3333],
];
const webPhotoUrl = (id, w, hgt) => `https://picsum.photos/id/${id}/${w}/${hgt}`;

// The photo at this chat pane's size in device pixels (in steps, so small
// resizes reuse the same download), never larger than the original.
function photoBgUrl(id) {
  const pane = $('#chat-pane');
  const dpr = window.devicePixelRatio || 1;
  let w = Math.ceil(((pane.clientWidth || 1200) * dpr) / 256) * 256;
  let hgt = Math.ceil(((pane.clientHeight || 800) * dpr) / 256) * 256;
  const [, , ow = 5000, oh = 3333] = WEB_PHOTOS.find(p => p[0] === id) || [];
  const over = Math.max(w / ow, hgt / oh);
  if (over > 1) {
    w = Math.floor(w / over);
    hgt = Math.floor(hgt / over);
  }
  return webPhotoUrl(id, w, hgt);
}

function openPhotoGallery(key, done) {
  const modal = h('div', { class: 'modal', onclick: e => e.target === modal && close() });
  const onKey = e => {
    if (e.key !== 'Escape') return;
    e.stopImmediatePropagation(); // just this window, not the dialog underneath
    close();
  };
  const close = () => {
    modal.remove();
    window.removeEventListener('keydown', onKey, true);
  };
  const current = state.view.backgrounds.get(key)?.photo;
  const grid = h('div', { class: 'photo-grid' }, ...WEB_PHOTOS.map(([id, author]) => h('button', {
    type: 'button',
    class: `photo-tile${current === id ? ' picked' : ''}`,
    title: `Photo by ${author} (Unsplash)`,
    onclick: () => {
      setBackground(key, { photo: id });
      close();
      done();
    },
  }, h('img', { src: webPhotoUrl(id, 240, 150), alt: '', loading: 'lazy' }))));
  modal.append(h('div', { class: 'dialog photo-dialog' },
    h('h2', {}, 'Photos'),
    h('p', {}, `${WEB_PHOTOS.length} free photos from Unsplash, each sharp at any window size and on the phone. Hover one to see who took it.`),
    grid,
    h('div', { class: 'row end' }, h('button', { class: 'btn', onclick: close }, 'Cancel'))));
  window.addEventListener('keydown', onKey, true);
  document.body.append(modal);
}

// A picture as a background: at most 1600 px across, as a JPEG, so it stays small to save and sync.
async function backgroundFromFile(file) {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
  const canvas = h('canvas', { width: Math.round(bmp.width * scale), height: Math.round(bmp.height * scale) });
  canvas.getContext('2d').drawImage(bmp, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.82);
}

// The choices as small tiles. key: a chat, or "*" for all chats.
function bgTiles(key, rerender) {
  const own = state.view.backgrounds.get(key);
  const pick = bg => {
    setBackground(key, bg);
    rerender();
  };
  const file = h('input', {
    type: 'file',
    accept: 'image/*',
    hidden: true,
    onchange: async () => {
      const f = file.files[0];
      file.value = '';
      if (!f) return;
      try {
        pick({ image: await backgroundFromFile(f) });
      } catch {
        toast("Couldn't read that picture; try a PNG or JPEG");
      }
    },
  });
  const tile = (label, cls, on, onclick, style = null) =>
    h('button', { type: 'button', class: `bg-tile ${cls}${on ? ' on' : ''}`, title: label, 'aria-label': label, style, onclick }, h('span', {}, label));
  return h('div', { class: 'bg-tiles' },
    key === '*'
      ? tile('None', 'bg-none', !own, () => pick(null))
      : tile('Same as all chats', 'bg-default-tile', !own, () => pick(null)),
    key === '*' ? null : tile('None', 'bg-none', own?.preset === 'none', () => pick({ preset: 'none' })),
    ...BACKGROUNDS.map(b => tile(b.name, `bg-${b.id}`, own?.preset === b.id, () => pick({ preset: b.id }))),
    own?.image ? tile('Your picture', 'bg-image-tile on', true, () => file.click(), `background-image:url("${own.image}")`) : null,
    own?.photo ? tile('Photo', 'bg-image-tile on', true, () => openPhotoGallery(key, rerender), `background-image:url("${webPhotoUrl(own.photo, 128, 128)}")`) : null,
    tile('More photos…', 'bg-web', false, () => openPhotoGallery(key, rerender), `background-image:url("${webPhotoUrl('1022', 128, 128)}")`),
    tile(own?.image ? 'Change picture…' : 'Your picture…', 'bg-upload', false, () => file.click()),
    file);
}

function backgroundSection(key, rerender) {
  return h('section', {},
    h('h3', {}, 'Background'),
    h('p', {}, 'Shown behind this chat, only in Switchboard. The one for all chats is in Settings → Appearance.'),
    bgTiles(key, rerender));
}

async function pictureFromFile(file) {
  const bmp = await createImageBitmap(file);
  const side = Math.min(bmp.width, bmp.height);
  const canvas = h('canvas', { width: 128, height: 128 });
  canvas.getContext('2d').drawImage(bmp, (bmp.width - side) / 2, (bmp.height - side) / 2, side, side, 0, 0, 128, 128);
  return canvas.toDataURL('image/webp', 0.85);
}

// chat: set for a group or channel (a picture, no name color). conv: the chat
// this was opened for, which gets the tag section.
function openPersonDialog(convKey, author, chat = null, conv = null) {
  const pkey = chat ? chatLookKey(chat) : personKey(convKey, author);
  const modal = h('div', { class: 'modal', onclick: e => e.target === modal && close() });
  const onKey = e => {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    close();
  };
  const close = () => {
    modal.remove();
    document.removeEventListener('keydown', onKey, true);
  };
  const file = h('input', {
    type: 'file',
    accept: 'image/*',
    hidden: true,
    onchange: async () => {
      const f = file.files[0];
      file.value = '';
      if (!f) return;
      try {
        change({ image: await pictureFromFile(f) });
      } catch {
        toast("Couldn't read that picture; try a PNG or JPEG");
      }
    },
  });
  const change = changes => {
    setLook(pkey, changes);
    render();
    if (conv && convKey === state.openKey) renderHeader(conv);
  };
  const render = () => {
    const look = lookOf(pkey) || {};
    modal.replaceChildren(h('div', { class: 'dialog person-dialog' },
      h('div', { class: 'person-head' },
        avatarEl(author.name, author.avatar, 'person-preview', chat ? { image: look.image } : look, chat ? chatBase(chat) : null),
        h('div', {},
          h('h2', { style: !chat && look.color ? `color:${look.color}` : null }, author.name),
          h('p', {}, 'Only you see these changes.'))),
      conv ? tagSection(conv, render) : null,
      conv ? backgroundSection(conv.key, render) : null,
      chat ? null : h('section', {},
        h('h3', {}, 'Name color'),
        h('div', { class: 'swatches' },
          h('button', { class: `swatch none${look.color ? '' : ' on'}`, title: 'Default', onclick: () => change({ color: null }) }),
          ...PERSON_COLORS.map(color => h('button', {
            class: `swatch${look.color === color ? ' on' : ''}`,
            style: `background:${color}`,
            title: color,
            onclick: () => change({ color }),
          })),
          h('input', {
            type: 'color',
            class: 'swatch-custom',
            title: 'Any color',
            value: look.color || '#888888',
            onchange: e => change({ color: e.target.value }),
          })),
        chat ? null : h('label', { class: 'edit-new' },
          h('input', { type: 'checkbox', checked: !!look.tint, disabled: !look.color, onchange: e => change({ tint: e.target.checked || null }) }),
          'Use it for their picture too')),
      h('section', {},
        h('h3', {}, 'Picture'),
        h('p', {}, chat
          ? look.image ? 'Shown as this chat\'s icon in Switchboard.' : 'Upload a picture to use as this chat\'s icon.'
          : look.image ? 'Your picture replaces theirs in Switchboard.' : 'Upload a picture to use instead of theirs.'),
        h('div', { class: 'row' },
          h('button', { class: 'btn', onclick: () => file.click() }, look.image ? 'Change picture…' : 'Upload picture…'),
          look.image ? h('button', { class: 'btn danger', onclick: () => change({ image: null }) }, 'Remove picture') : null)),
      h('div', { class: 'dialog-actions' }, h('button', { class: 'btn primary', onclick: close }, 'Done')),
      file));
  };
  render();
  document.body.append(modal);
  document.addEventListener('keydown', onKey, true);
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
  panel.replaceChildren(...gifPicker(sendGif, closeGifPanel));
  panel.hidden = false;
}

// The search box and results; onPick(gif) when one is clicked. Used by the chat and the thread.
function gifPicker(onPick, onClose) {
  const grid = h('div', { class: 'gif-grid' });
  const input = h('input', { type: 'search', placeholder: 'Search GIFs', spellcheck: 'false' });
  const load = async query => {
    grid.replaceChildren(h('div', { class: 'placeholder' }, 'Loading…'));
    try {
      const gifs = await sb.searchGifs(query);
      if (input.value.trim() !== query) return; // a newer search is on its way
      grid.replaceChildren(...(gifs.length ? gifs.slice(0, 40).map(g => {
        const video = h('video', { src: g.preview, loop: true, autoplay: true, playsinline: true, title: 'Send this GIF', onclick: () => onPick(g) });
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
    e.stopPropagation();
    if (e.key === 'Escape') onClose();
  });
  if (!MOBILE) setTimeout(() => input.focus());
  load('');
  return [h('div', { class: 'gif-head' }, input, h('button', { class: 'icon-btn', title: 'Close', onclick: onClose }, '✕')), grid];
}

// Sends a GIF (as a reply with opts.replyTo) and returns the message, drawn as the GIF.
async function postGif(key, g, opts) {
  const discord = state.convs.get(key)?.service === 'discord';
  const message = await sb.send(key, discord ? g.url : g.gif, opts);
  message.text = '';
  message.attachments = [discord ? { name: 'GIF', url: g.preview, isVideo: true } : { name: 'GIF', url: g.gif, isImage: true }];
  return message;
}

// Discord embeds its own Tenor links; elsewhere the direct .gif link previews as an image.
async function sendGif(g) {
  const key = state.openKey;
  const conv = state.convs.get(key);
  if (!conv) return;
  closeGifPanel();
  try {
    onMessage({ key, message: await postGif(key, g) });
    scrollToBottom();
  } catch (e) {
    toast(cleanError(e));
  }
}

// ----- threads, like iMessage: the original and its replies over a blurred
// chat, with a box to reply. Replies that also show in the chat (Mattermost,
// Discord) arrive there as usual; Slack keeps them in the thread. -----

let thread = null; // { key, rootId, add(message), close() } while one is open

// The message a reply joins: the thread's root (Mattermost, Slack), or the
// message itself, which then becomes the start of a thread (Discord).
const threadRootOf = m => m.threadRoot || m.replyTo?.id || m.id;

async function openThread(key, rootId, { reply = false } = {}) {
  thread?.close();
  closePopover?.();
  const conv = state.convs.get(key);
  if (!conv || !rootId) return;
  const group = conv.kind !== 'dm' || state.view.dmNames;
  let messages = [];
  const list = h('div', { class: 'thread-list' }, h('div', { class: 'placeholder' }, 'Loading…'));
  const input = h('textarea', { class: 'thread-input', rows: 1, placeholder: 'Reply', spellcheck: 'true' });
  const send = h('button', { class: 'send-btn', type: 'button', 'aria-label': 'Send reply', title: 'Send reply' }, '↑');
  // Files and GIFs, like the chat's own box: 📎, GIF, paste, or drop on the thread.
  let staged = [];
  const tray = h('div', { class: 'staged thread-staged', hidden: true });
  const gifBox = h('div', { class: 'gif-panel thread-gifs', hidden: true });
  const fileInput = h('input', { type: 'file', multiple: true, hidden: true });
  const attach = h('button', { type: 'button', class: 'attach-btn', title: 'Send files in this thread', 'aria-label': 'Send files' }, '📎');
  const gifBtn = h('button', { type: 'button', class: 'gif-btn', title: 'Send a GIF in this thread' }, 'GIF');
  const panel = h('div', { class: 'thread-panel' },
    h('div', { class: 'thread-head' },
      h('span', {}, 'Thread'),
      h('span', { class: 'thread-where' }, displayTitle(conv)),
      h('button', { class: 'thread-close', 'aria-label': 'Close', title: 'Close (Esc)', onclick: () => close() }, '✕')),
    list,
    gifBox,
    tray,
    h('div', { class: 'composer thread-composer' }, attach, fileInput, gifBtn, input, send));
  const overlay = h('div', { class: 'thread-overlay', onclick: e => e.target === overlay && close() }, panel);

  const draw = () => {
    if (!messages.length) return list.replaceChildren(h('div', { class: 'placeholder' }, 'The original message is no longer available.'));
    list.replaceChildren(...messages.map((m, i) => {
      const prev = messages[i - 1];
      const first = !sameRun(prev, m);
      const row = bubbleEl(m, {
        key,
        last: !sameRun(m, messages[i + 1]),
        showName: group && !m.isSelf && first,
        showAvatar: group && !m.isSelf,
        quote: false,
      });
      if (first) row.classList.add('first');
      if (i === 0) {
        row.classList.add('thread-root');
        row.title = 'Show it in the chat';
        row.addEventListener('click', e => {
          if (e.target.closest('a, img, video, button, .msg-author')) return;
          close();
          jumpToMessage(m.id, m.ts);
        });
      }
      return row;
    }), ...(messages.length === 1 ? [h('div', { class: 'thread-empty' }, 'No replies yet')] : []));
    list.scrollTop = list.scrollHeight;
  };

  // Esc closes the GIF search, then drops waiting files, then closes the thread.
  const onKey = e => {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    e.preventDefault();
    if (!gifBox.hidden) closeGifs();
    else if (staged.length) {
      staged = [];
      drawStaged();
    } else close();
  };
  const close = () => {
    overlay.remove();
    document.removeEventListener('keydown', onKey, true);
    if (thread?.close === close) thread = null;
  };
  thread = {
    key,
    rootId,
    close,
    add(message) {
      if (messages.some(m => m.id === message.id)) return;
      messages.push(message);
      draw();
    },
  };

  const drawStaged = () => {
    tray.hidden = !staged.length;
    tray.replaceChildren(...staged.map(f => stagedFileEl(f, () => {
      staged = staged.filter(x => x !== f);
      drawStaged();
    })));
  };
  const stage = fileList => {
    const files = [...(fileList || [])];
    const big = files.find(f => f.size > 50 * 1024 * 1024);
    if (big) return toast(`${big.name || 'That file'} is too large (50 MB at most)`);
    staged = [...staged, ...files];
    drawStaged();
    input.focus();
  };
  const closeGifs = () => {
    gifBox.hidden = true;
    gifBox.replaceChildren();
  };

  // A reply that was sent: into the thread, and into the chat where the service shows replies there.
  const deliver = async message => {
    const root = (state.messages.get(key) || []).find(m => m.id === rootId);
    if (!message || message.inThread) {
      if (root) {
        root.replyCount = (root.replyCount || 0) + 1;
        if (state.openKey === key) renderMessages(key);
      }
    }
    if (!message) {
      // Slack sends files without returning the message: read the thread again.
      const fresh = await sb.thread(key, rootId).catch(() => null);
      if (fresh && thread?.close === close) {
        messages = fresh;
        draw();
      }
      return;
    }
    if (!message.inThread) onMessage({ key, message }); // shows in the chat too (and in here, via onMessage)
    thread?.add(message);
  };

  const submit = async () => {
    const text = input.value.trim();
    const files = staged;
    if (!text && !files.length) return;
    input.value = '';
    input.style.height = 'auto';
    staged = [];
    drawStaged();
    try {
      if (files.length) {
        toast(`Sending ${files.length === 1 ? files[0].name || 'image' : `${files.length} files`}…`);
        await deliver(await sb.upload(key, await filePayload(files), text, { replyTo: rootId }));
        toast('Sent');
      } else {
        await deliver(await sb.send(key, text, { replyTo: rootId }));
      }
    } catch (e) {
      if (!input.value) input.value = text;
      if (files.length && !staged.length) {
        staged = files; // put them back to retry
        drawStaged();
      }
      toast(cleanError(e));
    }
  };
  attach.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    stage(fileInput.files);
    fileInput.value = '';
  });
  gifBtn.addEventListener('click', () => {
    if (!gifBox.hidden) return closeGifs();
    gifBox.replaceChildren(...gifPicker(async g => {
      closeGifs();
      try {
        await deliver(await postGif(key, g, { replyTo: rootId }));
      } catch (e) {
        toast(cleanError(e));
      }
    }, closeGifs));
    gifBox.hidden = false;
  });
  input.addEventListener('paste', e => {
    if (e.clipboardData?.files?.length) {
      e.preventDefault();
      stage(e.clipboardData.files);
    }
  });
  panel.addEventListener('dragover', e => {
    if (![...(e.dataTransfer?.types || [])].includes('Files')) return;
    e.preventDefault();
    e.stopPropagation();
    panel.classList.add('file-drop');
  });
  panel.addEventListener('dragleave', e => {
    if (!panel.contains(e.relatedTarget)) panel.classList.remove('file-drop');
  });
  panel.addEventListener('drop', e => {
    if (![...(e.dataTransfer?.types || [])].includes('Files')) return;
    e.preventDefault();
    e.stopPropagation();
    panel.classList.remove('file-drop');
    stage(e.dataTransfer.files);
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
  });
  input.addEventListener('keydown', e => {
    e.stopPropagation(); // keep the chat's shortcuts out of the reply box
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !MOBILE) {
      e.preventDefault();
      submit();
    }
  });
  send.addEventListener('mousedown', e => e.preventDefault()); // keep the keyboard up
  send.addEventListener('click', submit);

  document.addEventListener('keydown', onKey, true);
  document.body.append(overlay);
  if (reply || !MOBILE) setTimeout(() => input.focus(), 50);

  // The service's own thread when it has one; otherwise the loaded messages that reply to it.
  const loaded = state.messages.get(key) || [];
  const fromLoaded = () => {
    const root = loaded.find(m => m.id === rootId);
    return root ? [root, ...loaded.filter(m => m.id !== rootId && threadRootOf(m) === rootId)] : [];
  };
  try {
    messages = (await sb.thread(key, rootId)) || fromLoaded();
  } catch {
    messages = fromLoaded();
  }
  if (thread?.close !== close) return; // closed or replaced meanwhile
  draw();
}

const findRow = id => id && [...document.querySelectorAll('#messages .msg-row')].find(el => el.dataset.id === id);
const JUMP_PAGES = 30; // how far back a reply's original is looked for: about 1,500 messages

// Scrolls to a message, loading earlier history first when it isn't loaded yet.
// ts (when the provider knows it) stops the search once history passes that
// time. Switching chats or scrolling stops it too.
async function jumpToMessage(id, ts) {
  const key = state.openKey;
  const list = state.messages.get(key);
  let row = findRow(id);
  if (!row && key && list?.length && !state.loadingOlder) {
    state.loadingOlder = true;
    const started = Date.now();
    toast('Finding the original message…');
    let pages = 0;
    try {
      while (pages < JUMP_PAGES && !state.exhausted.has(key) && !list.some(m => m.id === id)) {
        if (ts && list[0].ts < ts) break; // already past it: the original was deleted
        const older = await sb.fetchMessages(key, list[0].id);
        pages++;
        if (older.length < PAGE) state.exhausted.add(key);
        const ids = new Set(list.map(m => m.id));
        list.unshift(...older.filter(m => !ids.has(m.id)));
        if (state.openKey !== key || (userScrolling() && userScrollAt > started)) break;
      }
    } catch (e) {
      toast(cleanError(e));
    } finally {
      state.loadingOlder = false;
    }
    if (state.openKey !== key) return;
    if (pages) {
      const box = $('#messages');
      const fromBottom = box.scrollHeight - box.scrollTop;
      renderMessages(key);
      box.scrollTop = box.scrollHeight - fromBottom;
    }
    row = findRow(id);
    if (row) $('#toast').hidden = true;
    else if (userScrollAt > started) return;
    else if (ts && list[0].ts < ts) return toast('The original message was deleted');
    else if (state.exhausted.has(key)) return toast("Couldn't find the original message");
    else return toast(`The original is more than ${(list.length / 1000).toFixed(1).replace('.0', '')}k messages back`);
  }
  if (!row) return toast('The original message is further back; scroll up to load it');
  stickToBottom = false; // stay on the quoted message even if pictures below finish loading
  jumpedAt = Date.now();
  const box = $('#messages');
  const far = Math.abs(row.getBoundingClientRect().top - box.getBoundingClientRect().top) > 3 * box.clientHeight;
  row.scrollIntoView({ block: 'center', behavior: far ? 'auto' : 'smooth' });
  row.classList.remove('flash');
  void row.offsetWidth; // restart the animation
  row.classList.add('flash');
}

function renderMessages(key) {
  hideReactTip();
  const list = state.messages.get(key) || [];
  if (!list.length) return showPlaceholder('No messages yet');
  // Names and pictures where several people talk, and in direct messages too unless turned off.
  const group = state.convs.get(key)?.kind !== 'dm' || state.view.dmNames;
  const nodes = [];
  if (state.exhausted.has(key)) nodes.push(h('div', { class: 'history-start' }, 'Beginning of conversation'));
  const mark = state.newMark?.key === key ? state.newMark : null;
  const markId = mark && (mark.id || list[Math.max(0, list.length - mark.count)]?.id);
  // Replies counted among the loaded messages (Discord has no count of its own).
  const replyCounts = new Map();
  for (const m of list) {
    const root = m.threadRoot || m.replyTo?.id;
    if (root) replyCounts.set(root, (replyCounts.get(root) || 0) + 1);
  }
  list.forEach((m, i) => {
    const prev = list[i - 1];
    if (markId && m.id === markId) nodes.push(h('div', { class: 'new-sep' }, h('span', {}, 'New')));
    if (!prev || dayKey(prev.ts) !== dayKey(m.ts) || m.ts - prev.ts > TIME_GAP) {
      nodes.push(h('div', { class: 'time-sep' }, h('b', {}, formatDay(m.ts)), ` ${formatTime(m.ts)}`));
    }
    if (m.system) {
      nodes.push(h('div', { class: 'system-msg' }, m.text));
      return;
    }
    const first = !sameRun(prev, m);
    nodes.push(bubbleEl(m, {
      key,
      last: !sameRun(m, list[i + 1]),
      showName: group && !m.isSelf && first,
      showAvatar: group && !m.isSelf,
      // Several messages in a row answering the same one show its quote once.
      quote: !(m.replyTo?.id && !first && prev?.replyTo?.id === m.replyTo.id),
      replies: Math.max(m.replyCount || 0, replyCounts.get(m.id) || 0),
    }));
    if (first) nodes[nodes.length - 1].classList.add('first');
  });
  $('#messages').replaceChildren(...nodes);
}

function scrollToBottom() {
  const box = $('#messages');
  box.scrollTop = box.scrollHeight;
  stickToBottom = true;
}

// When you last scrolled the chat yourself (trackpad, wheel, touch, keys,
// scrollbar). Scrolls without that are the page settling: pictures loading,
// a re-render. Those must not unstick the chat from the bottom.
let userScrollAt = 0;
let jumpedAt = 0; // a jump to a quoted message; its scrolling must not re-stick to the bottom
const userScrolling = () => Date.now() - userScrollAt < 1000;

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
  const rootId = message.threadRoot || message.replyTo?.id;
  if (isNew && rootId) {
    const root = list?.find(m => m.id === rootId);
    if (root && root.replyCount) root.replyCount += 1;
    if (thread?.key === key && thread.rootId === rootId) thread.add(message);
  }

  if (isNew && !message.isSelf && key === state.openKey && !document.hasFocus() && state.newMark?.key !== key) {
    state.newMark = { key, id: message.id };
  }
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

// ----- sharing from other apps (phone): "Send 1 picture to…" over the chat
// list; the chat you tap gets the files in its composer, ready to send. -----

function startShare(share) {
  if (share.failed) toast(`${share.failed === 1 ? 'One file' : `${share.failed} files`} couldn't be read from the other app`);
  else if (share.tooLarge) toast(`${share.tooLarge === 1 ? 'One file is' : `${share.tooLarge} files are`} too large to share (50 MB at most)`);
  if (!share.files.length && !share.text) return;
  state.share = share;
  if (!$('#settings').hidden) closeSettings();
  if (state.openKey) closeConversation();
  renderShareBar();
}

function shareLabel({ files, text }) {
  if (!files.length) return /^https?:\/\/\S+$/.test(text.trim()) ? 'a link' : 'text';
  const kind = files.every(f => f.type.startsWith('image/')) ? 'picture' : files.every(f => f.type.startsWith('video/')) ? 'video' : 'file';
  return files.length === 1 ? `1 ${kind}` : `${files.length} ${kind}s`;
}

function renderShareBar() {
  let bar = $('#share-bar');
  if (!state.share) return bar?.remove();
  if (!bar) {
    bar = h('div', { id: 'share-bar', class: 'share-bar' });
    $('#sidebar .drag').after(bar);
  }
  bar.replaceChildren(
    h('span', {}, `Send ${shareLabel(state.share)} to…`),
    h('button', { class: 'link-btn', onclick: () => cancelShare() }, 'Cancel'));
}

function cancelShare() {
  state.share = null;
  renderShareBar();
}

// Called when a chat opens while something is waiting to be shared.
function deliverShare() {
  const { files, text } = state.share;
  state.share = null;
  renderShareBar();
  if (files.length) stageFiles(files);
  if (text) {
    const input = $('#composer-input');
    input.value = input.value ? `${input.value} ${text}` : text;
    autosize();
    input.focus();
  }
}

function closeConversation() {
  closePopover?.();
  state.newMark = null;
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
  if (state.newMark?.key === key) state.newMark = null; // you've replied, so it's all been seen
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
const DROPPED_NAMES = { people: "people's colors", keys: 'hidden chats', assign: 'groups', nicknames: 'nicknames' };

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
        dropped.length ? h('p', {}, `Too much to fit, so these stay on the Mac: ${dropped.map(k => DROPPED_NAMES[k] || k).join(', ')}.`) : null,
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

function tagsSection() {
  const tags = state.view.tags;
  return h('section', {},
    h('h3', {}, 'Tags'),
    h('p', {}, tags.length
      ? `Rename, recolor or delete tags here, or ${MOBILE ? 'long-press' : 'right-click'} a tag above the chat list. Put a tag on a chat from its menu (Tag) or by clicking its picture at the top of the chat.${MOBILE ? '' : ' ⌘1–⌘9 show just the 1st–9th tag; the same key again shows everything.'}`
      : (MOBILE ? 'Long-press' : 'Right-click') + ' a chat → Tag → New tag… to make your first tag, e.g. "CMS" or "Students".'),
    ...tags.map((t, i) => h('div', { class: 'row tag-row' },
      MOBILE ? null : h('span', { class: 'tag-key' }, i < 9 ? `⌘${i + 1}` : ''),
      h('input', { type: 'color', class: 'swatch-custom', value: t.color, title: 'Tag color', onchange: e => { updateTag(t.id, { color: e.target.value }); renderSettings(); } }),
      h('input', { value: t.name, maxlength: '40', placeholder: 'Tag name', oninput: e => e.target.value.trim() && updateTag(t.id, { name: e.target.value.trim() }) }),
      h('span', { class: 'edit-count' }, `${[...state.convs.values()].filter(c => tagFor(c)?.id === t.id).length} chats`),
      h('button', { class: 'btn small', title: 'Move up', disabled: i === 0, onclick: () => { moveTag(i, -1); renderSettings(); } }, '↑'),
      h('button', { class: 'btn small', title: 'Move down', disabled: i === tags.length - 1, onclick: () => { moveTag(i, 1); renderSettings(); } }, '↓'),
      h('button', { class: 'btn danger small', onclick: () => { deleteTag(t.id); renderSettings(); } }, 'Delete'))));
}

// ----- size: the whole app (zoom) and message text (chatText) -----

const ZOOM_STEPS = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];
const CHAT_TEXT_STEPS = [0.85, 1, 1.15, 1.3, 1.5];

function applyDisplay() {
  document.body.style.setProperty('--chat-scale', String(state.display?.chatText || 1));
}

function stepDisplay(field, steps, dir) {
  const now = state.display[field];
  const i = steps.indexOf(now);
  const next = dir === 0 ? 1 : steps[Math.min(steps.length - 1, Math.max(0, (i === -1 ? steps.indexOf(1) : i) + dir))];
  if (next === now) return;
  sb.setDisplay({ [field]: next }).then(d => {
    state.display = d;
    applyDisplay();
    renderSettings();
    if (field === 'chatText' && stickToBottom) scrollToBottom();
  }).catch(e => toast(cleanError(e)));
}

function sizeRow(label, field, steps) {
  const value = state.display[field];
  return h('div', { class: 'row size-row' },
    h('span', { class: 'size-label' }, label),
    h('button', { class: 'btn small', disabled: value <= steps[0], 'aria-label': `${label} smaller`, onclick: () => stepDisplay(field, steps, -1) }, '−'),
    h('span', { class: 'size-value' }, `${Math.round(value * 100)}%`),
    h('button', { class: 'btn small', disabled: value >= steps[steps.length - 1], 'aria-label': `${label} bigger`, onclick: () => stepDisplay(field, steps, 1) }, '+'),
    value !== 1 ? h('button', { class: 'link-btn', onclick: () => stepDisplay(field, steps, 0) }, 'Reset') : null);
}

function appearanceSection() {
  return h('section', {},
    h('h3', {}, 'Appearance'),
    h('div', { class: 'bg-default' }, h('span', { class: 'size-label' }, 'Background for all chats'), bgTiles('*', () => renderSettings())),
    sizeRow(MOBILE ? 'Text size' : 'Size of everything', 'zoom', ZOOM_STEPS),
    sizeRow('Message text', 'chatText', CHAT_TEXT_STEPS),
    MOBILE ? null : h('p', {}, 'Shortcuts: ⌘+ bigger, ⌘− smaller, ⌘0 actual size. Message text sizes the chat on top of that.'),
    h('label', { class: 'edit-new' },
      h('input', { type: 'checkbox', checked: state.view.compact, onchange: e => setCompact(e.target.checked) }),
      'Compact chat list'),
    h('label', { class: 'edit-new' },
      h('input', { type: 'checkbox', checked: state.view.flat, onchange: e => setFlat(e.target.checked) }),
      'Latest first (ignore groups; newest message at the top)'),
    h('label', { class: 'edit-new' },
      h('input', { type: 'checkbox', checked: state.view.bigPictures, onchange: e => setBigPictures(e.target.checked) }),
      'Bigger pictures next to messages'),
    h('label', { class: 'edit-new' },
      h('input', { type: 'checkbox', checked: state.view.dmNames, onchange: e => setDmNames(e.target.checked) }),
      'Names and pictures in direct messages too'),
    h('label', { class: 'edit-new' },
      h('input', { type: 'checkbox', checked: state.view.showTimes, onchange: e => setShowTimes(e.target.checked) }),
      'Times under messages'),
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
  // Redrawing (an account reconnecting, sync finishing) would wipe what is being
  // typed, so wait until the field is left.
  const typing = document.activeElement;
  if ($('#settings').contains(typing) && typing.matches('input:not([type=color]):not([type=checkbox]), textarea')) {
    if (!typing.dataset.redrawLater) {
      typing.dataset.redrawLater = '1';
      typing.addEventListener('blur', () => setTimeout(() => !$('#settings').hidden && renderSettings()), { once: true });
    }
    return;
  }
  const s = state.settings;
  const children = [h('h2', {}, MOBILE ? 'Settings' : 'Accounts')];
  if (MOBILE) children.push(phoneAccountsSection());
  else if (s.demo) children.push(h('p', {}, 'Demo mode: showing sample conversations. Run the app normally to connect real accounts.'));
  else children.push(discordSection(), mattermostSection(), slackSection(), webAppsSection(), syncSection(), phoneSection());
  children.push(appearanceSection());
  children.push(tagsSection());
  children.push(h('div', { class: 'dialog-actions' }, h('button', { class: 'btn', onclick: closeSettings }, 'Done')));
  $('#settings .dialog').replaceChildren(...children);
}

function openSettings() {
  renderSettings();
  $('#settings').hidden = false;
  if (!MOBILE && !state.settings.demo) {
    sb.syncStatus().then(st => {
      state.sync = st;
      if (!$('#settings').hidden) renderSettings();
    }).catch(() => {});
  }
}

// ----- sync between Macs -----

const syncPlace = folder => String(folder || '')
  .replace(/^.*\/CloudStorage\/OneDrive[^/]*/, 'OneDrive')
  .replace(/^.*\/Mobile Documents\/com~apple~CloudDocs/, 'iCloud Drive')
  .replace(/^\/Users\/[^/]+/, '~')
  .split('/').filter(Boolean).join(' › ');

async function runSync(btn, fn) {
  btn.disabled = true;
  try {
    state.sync = await fn();
    renderSettings();
  } catch (e) {
    toast(cleanError(e));
    btn.disabled = false;
  }
}

function syncSection() {
  const st = state.sync;
  const title = h('h3', {}, 'Sync between Macs');
  if (!st) return h('section', {}, title, h('p', {}, 'Checking…'));
  if (!st.enabled) {
    const on = h('button', { class: 'btn primary', onclick: () => runSync(on, () => sb.syncEnable()) }, 'Turn on with OneDrive');
    const choose = h('button', { class: 'btn', onclick: () => runSync(choose, () => sb.syncChoose()) }, 'Choose folder…');
    return h('section', {}, title,
      h('p', {}, "Keeps groups, pins, nicknames, hidden chats, people's colors and pictures, and web apps the same on your Macs, through a folder both of them sync. If the folder already has your other Mac's settings, this Mac switches to them."),
      h('div', { class: 'row' }, st.suggested ? on : null, choose),
      h('p', {}, st.suggested ? `Folder: ${syncPlace(st.suggested)}` : 'No OneDrive folder found on this Mac; choose a folder that syncs.'));
  }
  const last = st.lastSync;
  const lastText = last
    ? `Last synced ${formatListTime(last.at)}: ${last.what} ${last.from === st.device ? 'sent from this Mac' : `from ${last.from}`}.`
    : 'Nothing synced yet.';
  const now = h('button', { class: 'btn', onclick: () => runSync(now, () => sb.syncNow()) }, 'Sync now');
  const change = h('button', { class: 'btn', onclick: () => runSync(change, () => sb.syncChoose()) }, 'Change folder…');
  const off = h('button', { class: 'btn danger', onclick: () => runSync(off, () => sb.syncDisable()) }, 'Turn off');
  const items = [title,
    h('p', {}, `Syncing through ${syncPlace(st.folder)}. ${lastText}`),
    st.error ? h('p', { style: 'color:#e5484d' }, st.error) : null,
    h('div', { class: 'row' }, now, change, off)];
  if (st.hasPassphrase) {
    items.push(h('p', {}, 'Logins sync too, encrypted with your passphrase. Signing in or out here does the same on your other Mac.'));
  } else {
    const pass = h('input', { type: 'password', placeholder: 'Passphrase, the same on each Mac', autocomplete: 'new-password' });
    const save = h('button', { class: 'btn', onclick: () => runSync(save, () => sb.syncPassphrase(pass.value)) }, 'Sync logins');
    pass.addEventListener('keydown', e => e.key === 'Enter' && save.click());
    items.push(
      h('p', {}, "Logins can sync too. They're stored in the folder encrypted with a passphrase; type the same one on your other Mac. Teams signs in separately on each Mac."),
      h('div', { class: 'row' }, pass, save));
  }
  return h('section', {}, ...items);
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
  else if (action.startsWith('tag:')) showTag(Number(action.slice(4)));
  else if (action === 'back') {
    // Android back button: close whatever is on top, else leave the app.
    if (closePopover) closePopover();
    else if (document.querySelector('.lightbox')) document.querySelector('.lightbox').click(); // its own close
    else if (closeChannelInfo) closeChannelInfo();
    else if (thread) thread.close();
    else if (!$('#settings').hidden) closeSettings();
    else if (state.renamingConv || state.renaming) document.activeElement?.blur();
    else if (state.editing) setEditing(false);
    else if (state.share) cancelShare();
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
  // Tapping Send would otherwise take focus from the text box, which closes the
  // phone keyboard after every message.
  $('#composer .send-btn').addEventListener('mousedown', e => e.preventDefault());
  $('#composer .send-btn').addEventListener('touchend', e => {
    if (!MOBILE) return;
    e.preventDefault(); // no focus change, no synthetic click
    sendMessage();
  });
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
  for (const type of ['wheel', 'touchmove', 'pointerdown', 'keydown']) {
    $('#messages').addEventListener(type, () => { userScrollAt = Date.now(); }, { passive: true });
  }
  $('#messages').addEventListener('scroll', e => {
    const box = e.target;
    const jumping = Date.now() - jumpedAt < 1500 && !userScrolling();
    if (box.scrollHeight - box.scrollTop - box.clientHeight < 60) {
      if (!jumping) stickToBottom = true;
    } else if (userScrolling()) stickToBottom = false;
    if (box.scrollTop < 150) loadOlder();
  });
  // Pictures, GIFs and custom emoji only get their height once loaded. When
  // that happens at the bottom (a picture you just sent), follow it down.
  for (const type of ['load', 'loadedmetadata']) {
    $('#messages').addEventListener(type, () => {
      if (stickToBottom) scrollToBottom();
    }, true);
  }
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
  // Coming back to the window: the open chat's unread dot and the Dock count
  // stay a moment so you can see where the new messages were (the "New" line
  // marks them), then clear. Leaving again before that keeps them unread.
  let readTimer;
  window.addEventListener('focus', () => {
    clearTimeout(readTimer);
    const key = state.openKey;
    readTimer = setTimeout(() => {
      const conv = state.convs.get(key);
      if (!document.hasFocus() || state.openKey !== key || !conv || !(conv.unread || conv.mentions)) return;
      conv.unread = false;
      conv.mentions = 0;
      conv.unreadCount = 0;
      sb.markRead(conv.key).catch(() => {});
      scheduleRender();
    }, 2500);
  });
  window.addEventListener('blur', () => clearTimeout(readTimer));
}

function viewFrom(v = {}) {
  return {
    mode: v.mode || 'all',
    keys: new Set(v.keys || []),
    groups: v.groups || [],
    assign: new Map(Object.entries(v.assign || {})),
    nicknames: new Map(Object.entries(v.nicknames || {})),
    people: new Map(Object.entries(v.people || {})),
    pins: Array.isArray(v.pins) ? v.pins.map(String) : [],
    otherCollapsed: !!v.otherCollapsed,
    compact: !!v.compact,
    flat: !!v.flat,
    bigPictures: v.bigPictures !== false, // on unless turned off
    dmNames: v.dmNames !== false,
    showTimes: v.showTimes !== false,
    tags: Array.isArray(v.tags) ? v.tags : [],
    tagOf: new Map(Object.entries(v.tagOf || {})),
    backgrounds: new Map(Object.entries(v.backgrounds || {})),
  };
}

async function init() {
  if (MOBILE) {
    document.body.classList.add('mobile');
    $('#search').placeholder = 'Search';
  }
  const initial = await sb.getState();
  state.settings = initial.settings;
  try {
    state.dmOnly = localStorage.getItem('dmOnly') === '1'; // remembered on this computer only
  } catch {}
  state.display = initial.settings.display || { zoom: 1, chatText: 1 };
  applyDisplay();
  state.statuses = initial.statuses;
  state.view = viewFrom(initial.settings.view);
  migrateChatColors();
  for (const c of initial.conversations) state.convs.set(c.key, c);

  sb.on('conversations', ({ provider, list }) => {
    const before = state.convs.get(state.openKey);
    for (const [key, c] of state.convs) if (c.provider === provider) state.convs.delete(key);
    for (const c of list) state.convs.set(c.key, c);
    const now = state.convs.get(state.openKey);
    if (before && now && (now.topic !== before.topic || now.title !== before.title)) renderHeader(now);
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
  sb.on('shared', startShare); // phone: shared from another app
  // Size changed with ⌘+ / ⌘− / ⌘0 (or in Settings).
  sb.on('display', d => {
    state.display = d;
    applyDisplay();
    if (!$('#settings').hidden) renderSettings();
  });
  // Settings changed by the other Mac (sync) or by signing in there.
  sb.on('settings', s => {
    state.settings = s;
    state.view = viewFrom(s.view);
    applyChatBackground();
    syncWebviews();
    scheduleRender();
    if (state.openKey && state.messages.has(state.openKey)) {
      const box = $('#messages');
      const top = box.scrollTop;
      renderMessages(state.openKey);
      box.scrollTop = stickToBottom ? box.scrollHeight : top;
    }
    if (!$('#settings').hidden) renderSettings();
  });
  sb.on('sync', st => {
    state.sync = st;
    if (!$('#settings').hidden) renderSettings();
  });

  bindUi();
  syncWebviews();
  renderStatus();
  renderSidebar();
  updateBadge();

  const s = state.settings;
  if (!s.demo && !s.hasDiscord && !s.hasMattermost && !s.slack.length) openSettings();
}

init();
