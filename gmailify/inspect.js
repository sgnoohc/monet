// gmailify/inspect.js
// Paste into the DevTools console on outlook.cloud.microsoft to see which of
// gmailify's selectors actually match this OWA build, and to harvest stable
// hooks for the ones that don't.
//
//   gmailify.check()      which selectors hit, which are dead
//   gmailify.hooks()      stable attributes present on the page
//   gmailify.at()         click an element, then call this for its ancestry
//   gmailify.date()       the open message's date + body container (hashed nodes)
//   gmailify.attach()     the attachment well's layout, node by node
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
      // Classes too: a hashed one is a poor hook, but on nodes OWA gives no
      // attribute at all — the date, the subject box — it is the only one.
      const cls = (typeof n.className === 'string' ? n.className : '').trim();
      if (cls) bits.push('.' + cls.split(/\s+/).join('.'));
      if (n.hasAttribute('title')) bits.push(`  title="${n.getAttribute('title').slice(0, 60)}"`);
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

  // Run this with a message OPEN. Finds the date/time in the message header
  // and the container the body text is rendered in — the two nodes whose type
  // is set in section 6 and which no stable attribute names. Prints a
  // paste-ready selector for each, since both are hashed classes in the end.
  const date = () => {
    const pane = document.querySelector('[role="main"][aria-label="Reading Pane"]');
    if (!pane) return console.warn('open a message first');
    const DATEISH = /^(?:\w{3},?\s)?(?:\d{1,2}[\/.-]\d{1,2}[\/.-]\d{2,4}|\w{3,9}\s\d{1,2})?[\s,]*(?:\d{1,2}:\d{2}\s?[AP]M)?$/i;
    const sel = (el) => {
      const cls = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/)
        .filter(c => c && !c.startsWith('fui-'));
      return el.id ? `#${el.id}`
        : cls.length ? `${el.tagName.toLowerCase()}.${cls[0]}`
        : el.getAttribute('title') ? `${el.tagName.toLowerCase()}[title]` : el.tagName.toLowerCase();
    };
    console.group('date-shaped nodes in the message header');
    for (const el of pane.querySelectorAll('span, div, time')) {
      if (el.children.length) continue;
      const t = el.textContent.trim();
      if (!t || t.length > 32 || !/\d/.test(t) || !DATEISH.test(t)) continue;
      const cs = getComputedStyle(el);
      console.log(`${JSON.stringify(t)}  fs=${cs.fontSize} lh=${cs.lineHeight} ` +
        `color=${cs.color} title=${JSON.stringify(el.getAttribute('title'))}\n  selector: ` +
        `[aria-label="Email message"] ${sel(el)}`);
    }
    console.groupEnd();

    console.group('message body containers');
    const BODY = ['[id^="UniqueMessageBody"]', '[aria-label="Message body"]',
                  '.allowTextSelection', '.PlainText', '[class*="rps_"]'];
    for (const s of BODY) {
      const hits = pane.querySelectorAll(s);
      console.log(`${hits.length ? '✔' : '✘'} ${String(hits.length).padStart(3)}  ${s}` +
        (hits.length ? `  → fs=${getComputedStyle(hits[0]).fontSize} ` +
          `ff=${getComputedStyle(hits[0]).fontFamily.split(',')[0]}` : ''));
    }
    // Whatever actually holds the text, in case none of the above matched.
    const longest = [...pane.querySelectorAll('div')]
      .filter(el => el.textContent.trim().length > 200)
      .sort((a, b) => a.getElementsByTagName('*').length - b.getElementsByTagName('*').length)[0];
    if (longest) console.log('deepest node holding the letter:', sel(longest),
      `fs=${getComputedStyle(longest).fontSize} ff=${getComputedStyle(longest).fontFamily.split(',')[0]}`);
    console.groupEnd();
  };

  // Run this with a message that HAS an attachment open. Walks the attachment
  // well from the listbox down to the chevron and prints what each node is
  // doing dimensionally — width, display, flex, min-width, the lot — because
  // the thing that holds the tile at full width is a hashed div with no
  // attribute on it, and only the computed values say which one.
  const attach = () => {
    const box = document.querySelector('[role="listbox"][aria-label="file attachments"]');
    if (!box) return console.warn('open a message with an attachment first');
    const walk = (el, depth) => {
      const cs = getComputedStyle(el);
      const cls = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/)
        .filter(c => c && !c.startsWith('fui-') && !c.startsWith('ms-')).join('.');
      console.log(
        `${'  '.repeat(depth)}<${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}` +
        `${el.getAttribute('role') ? `[role=${el.getAttribute('role')}]` : ''}> ` +
        `w=${Math.round(el.getBoundingClientRect().width)} css-w=${cs.width} ` +
        `max=${cs.maxWidth} min=${cs.minWidth} display=${cs.display} ` +
        `flex=${cs.flexGrow}/${cs.flexShrink}/${cs.flexBasis} justify=${cs.justifyContent}`);
      if (depth < 6) for (const kid of el.children) walk(kid, depth + 1);
    };
    console.log(`well width ${Math.round(box.getBoundingClientRect().width)}px, ` +
      `pane width ${Math.round((document.querySelector('[role="main"][aria-label="Reading Pane"]') || box).getBoundingClientRect().width)}px`);
    walk(box, 0);
    return box;
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

  // Run this WHILE a new-mail toast is on screen. Prints what the toast
  // actually is and which ancestor is constraining its height.
  const toast = () => {
    const found = document.querySelector(
      '[data-app-section="NotificationPane"], [class*="fui-Toast"], [role="alert"]');
    if (!found) return console.warn('no toast on screen — trigger one and re-run');
    console.log('matched:', found.tagName.toLowerCase(),
      found.getAttribute('data-app-section') || found.className);
    for (let el = found; el && el !== document.body; el = el.parentElement) {
      const cs = getComputedStyle(el), r = el.getBoundingClientRect();
      const clipped = el.scrollHeight > Math.ceil(r.height) + 1;
      console.log(
        `${clipped ? 'CLIPPED ' : '        '}<${el.tagName.toLowerCase()}` +
        `${el.id ? '#' + el.id : ''} ${(typeof el.className === 'string' ? el.className : '').slice(0, 40)}> ` +
        `h=${Math.round(r.height)} scrollH=${el.scrollHeight} ` +
        `css-height=${cs.height} max=${cs.maxHeight} overflow=${cs.overflow} lh=${cs.lineHeight}`);
    }
    return found;
  };

  window.gmailify = { check, hooks, at, tokens, rail, row, date, attach, opaque, panes, toast };
  console.log('gmailify: try gmailify.check(), gmailify.hooks(), gmailify.at(), gmailify.rail(), gmailify.row(), gmailify.date(), gmailify.attach(), gmailify.opaque(), gmailify.panes(), gmailify.toast(), gmailify.tokens()');
})();
