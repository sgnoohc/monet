// gmailify/inspect.js
// Paste into the DevTools console on outlook.cloud.microsoft to see which of
// gmailify's selectors actually match this OWA build, and to harvest stable
// hooks for the ones that don't.
//
//   gmailify.check()      which selectors hit, which are dead
//   gmailify.hooks()      stable attributes present on the page
//   gmailify.at()         click an element, then call this for its ancestry
//   gmailify.tokens()     Fluent CSS variables currently in effect

(() => {
  const SELECTORS = {
    header:    ['#headerRow', '[data-app-section="AppHeader"]', '#O365_NavHeader'],
    search:    ['#topSearchInput', '[role="search"]', '[aria-label="Search"]'],
    nav:       ['[data-app-section="FolderPaneContainer"]', '#folderPaneDroppableContainer',
                'div[role="navigation"]', '[role="treeitem"]'],
    compose:   ['button[aria-label="New mail"]', 'button[aria-label^="New mail"]'],
    list:      ['[data-app-section="MessageList"]', '#MailList',
                'div[role="listbox"] > div[role="option"]', 'div[role="option"][data-convid]'],
    reading:   ['#ReadingPaneContainerId', '[data-app-section="ConversationContainer"]'],
    ribbon:    ['[data-app-section="RibbonTabs"]', '#ribbonContainer', 'div[aria-label="Ribbon"]'],
    toolbar:   ['[data-app-section="CommandBar"]', 'div[role="toolbar"]'],
    declutter: ['div[aria-label="Advertisement"]', '[data-app-section="RightRail"]',
                '[aria-label="My Day"]', 'div[aria-label*="Copilot"]'],
  };

  const check = () => {
    for (const [group, sels] of Object.entries(SELECTORS)) {
      console.group(group);
      for (const sel of sels) {
        const n = document.querySelectorAll(sel).length;
        console.log(`${n ? '✔' : '✘'} ${String(n).padStart(4)}  ${sel}`);
      }
      console.groupEnd();
    }
  };

  // Every data-app-section / role / aria-label value on the page, with counts.
  // These are the attributes Microsoft keeps stable across builds; hashed
  // `fui-*` and `___xxxxx` classes are not worth targeting.
  const hooks = () => {
    for (const attr of ['data-app-section', 'role', 'aria-label']) {
      const counts = new Map();
      for (const el of document.querySelectorAll(`[${attr}]`)) {
        const v = el.getAttribute(attr);
        counts.set(v, (counts.get(v) || 0) + 1);
      }
      console.group(`${attr} (${counts.size} distinct)`);
      console.table([...counts].sort((a, b) => b[1] - a[1]).slice(0, 60)
        .map(([value, count]) => ({ value, count })));
      console.groupEnd();
    }
  };

  // Ancestry of the last element you clicked in the Elements panel ($0).
  const at = (el) => {
    el = el || window.$0;
    if (!el) return console.warn('select an element in the Elements panel first');
    const chain = [];
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      const bits = [n.tagName.toLowerCase()];
      if (n.id) bits.push(`#${n.id}`);
      for (const a of ['data-app-section', 'role', 'aria-label', 'data-convid', 'aria-selected']) {
        if (n.hasAttribute(a)) bits.push(`[${a}="${n.getAttribute(a)}"]`);
      }
      chain.push(bits.join(''));
    }
    console.log(chain.reverse().join('\n  > '));
  };

  // Which Fluent tokens this build actually reads — the ones worth overriding.
  const tokens = () => {
    const cs = getComputedStyle(document.body);
    const found = [];
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch { continue; } // cross-origin
      for (const rule of rules || []) {
        if (!rule.style) continue;
        for (const prop of rule.style) {
          if (prop.startsWith('--') && !found.includes(prop)) found.push(prop);
        }
      }
    }
    console.table(found.sort().map(name => ({ name, value: cs.getPropertyValue(name).trim() })));
  };

  // Find the left app rail by the apps it links to, then print the ancestor
  // worth targeting. Use this when the rail survives an OWA rename.
  const rail = () => {
    const APPS = ['mail', 'calendar', 'people', 'to do', 'todo', 'files', 'groups', 'chat'];
    const hits = [...document.querySelectorAll('[aria-label],[title]')].filter(el => {
      const label = (el.getAttribute('aria-label') || el.getAttribute('title') || '').toLowerCase();
      return APPS.includes(label.trim());
    });
    if (!hits.length) return console.warn('no app-rail buttons found');
    // Deepest node that contains all of them is the rail container.
    let container = hits[0];
    while (container && !hits.every(h => container.contains(h))) container = container.parentElement;
    console.log('rail container:');
    at(container);
    console.log('candidate selectors:');
    for (const n of [container, container.parentElement]) {
      if (!n) continue;
      if (n.id) console.log(`  #${n.id}`);
      for (const a of ['data-app-section', 'aria-label', 'role']) {
        if (n.hasAttribute(a)) console.log(`  ${n.tagName.toLowerCase()}[${a}="${n.getAttribute(a)}"]`);
      }
    }
    return container;
  };

  // Print the skeleton of one message-list row: every node's tag, role, ids,
  // stable attributes, its computed height/padding/font, and a text sample.
  // This is the one dump that makes list styling precise instead of guesswork.
  const row = (n = 0) => {
    const rows = document.querySelectorAll(
      'div[role="grid"] div[role="row"], div[role="listbox"] > div[role="option"], div[role="option"][data-convid]');
    if (!rows.length) return console.warn('no list rows found');
    const target = rows[n];
    console.log(`row ${n} of ${rows.length}, outer height ${target.getBoundingClientRect().height}px`);
    const walk = (el, depth) => {
      const cs = getComputedStyle(el);
      const attrs = ['role', 'data-app-section', 'aria-label', 'data-convid', 'title']
        .filter(a => el.hasAttribute(a))
        .map(a => `${a}="${el.getAttribute(a).slice(0, 40)}"`)
        .join(' ');
      const text = (el.childNodes.length === 1 && el.firstChild.nodeType === 3)
        ? ` ← ${JSON.stringify(el.textContent.trim().slice(0, 40))}` : '';
      console.log(
        `${'  '.repeat(depth)}<${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''} ${attrs}> ` +
        `[h=${Math.round(el.getBoundingClientRect().height)} ` +
        `pad=${cs.paddingTop}/${cs.paddingBottom} lh=${cs.lineHeight} fs=${cs.fontSize} ` +
        `ff=${cs.fontFamily.split(',')[0]}]${text}`);
      if (depth < 5) for (const kid of el.children) walk(kid, depth + 1);
    };
    walk(target, 0);
    return target;
  };

  // What is covering the background image: every element bigger than a quarter
  // of the viewport that paints an opaque colour or an image of its own.
  const opaque = () => {
    const bodyBg = getComputedStyle(document.body).backgroundImage;
    console.log('body background-image:', bodyBg === 'none' ? 'NONE — the style never applied'
      : `${bodyBg.slice(0, 48)}… (${bodyBg.length} chars)`);
    const viewport = innerWidth * innerHeight;
    const hits = [];
    for (const el of document.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      const area = r.width * r.height;
      if (area < viewport * 0.25) continue;
      const cs = getComputedStyle(el);
      const solid = cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)'
        && !/,\s*0\)$/.test(cs.backgroundColor);
      if (!solid && cs.backgroundImage === 'none') continue;
      hits.push({
        el: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
          + (el.dataset.appSection ? `[${el.dataset.appSection}]` : '')
          + (typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/)[0] : ''),
        cover: Math.round(area / viewport * 100) + '%',
        bg: cs.backgroundColor,
        img: cs.backgroundImage.slice(0, 30),
      });
    }
    console.table(hits.slice(0, 30));
    return hits;
  };

  // Top edges of the two panes, for lining them up.
  const panes = () => {
    const list = document.querySelector('[role="complementary"][aria-label="Message list"]');
    const read = document.querySelector('[role="main"][aria-label="Reading Pane"]');
    if (!list || !read) return console.warn('open a message first — both panes must be visible');
    const a = list.getBoundingClientRect(), b = read.getBoundingClientRect();
    console.log(`message list top: ${a.top}\nreading pane top: ${b.top}\n--gm-read-top should be ${Math.round(a.top - b.top)}px`);
    return Math.round(a.top - b.top);
  };

  window.gmailify = { check, hooks, at, tokens, rail, row, opaque, panes };
  console.log('gmailify: try gmailify.check(), gmailify.hooks(), gmailify.at(), gmailify.rail(), gmailify.row(), gmailify.opaque(), gmailify.panes(), gmailify.tokens()');
})();
