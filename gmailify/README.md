# gmailify

A userstyle that reskins **outlook.cloud.microsoft** (Outlook Web / OWA) to look
like Gmail — Gmail's canvas and rounded panes, the Compose pill, right-rounded
folder pills, Gmail's single-line message rows, no ribbon, no ads or Copilot rail.

It's cosmetic only: no scripts, no network calls, nothing touches mail data.

## Install

**On any machine, one click:** open this in Chrome with
[Stylus](https://add0n.com/stylus.html) installed —

```
https://raw.githubusercontent.com/sgnoohc/monet/main/gmailify/gmailify.user.css
```

Stylus shows an install page; click **Install**. The style carries an
`@updateURL`, so Stylus will pull later versions from the same place (Manage →
Check for updates). Nothing needs to be cloned.

**From a local clone**, install `file:///path/to/monet/gmailify/gmailify.user.css`
after enabling **Allow access to file URLs** for Stylus in `chrome://extensions`
→ Stylus → Details. Edit `gmailify.css`, run `./build.sh`, reopen that URL,
click **Reinstall**.

It only applies to `outlook.cloud.microsoft`, `outlook.office.com`,
`outlook.office365.com` and `outlook.live.com` — the `@-moz-document` block at
the top of the built file. It is cosmetic only: no scripts, no network calls,
nothing touches mail data.

### Making it look exactly like the screenshots

Two things are deliberately NOT committed, because publishing them would
redistribute Google's assets:

```sh
./fonts.sh --google-sans                              # Google Sans + Google Sans Text
./background.sh ~/Pictures/bg.jpg                     # a background photo
LOCAL=1 ./build.sh gmailify.css gmailify.local.user.css
```

Install `gmailify.local.user.css` instead. It, `fonts.local.css` and
`background.css` are gitignored, and the two builds use separate font files so a
plain `./build.sh` cannot strip Google Sans out of your local copy. Rebuild
yours with the `LOCAL=1` line after any edit.

Without the first, the UI falls back to Roboto, which is what Gmail's own font
stack falls back to as well. Without the second you get a gradient instead of a
photo. Both are personal-machine steps; don't commit their output.

Working on this with Claude Code? `CLAUDE.md` in this directory carries the
install steps, the verified Outlook selectors, and the five rules that keep the
app from flickering or losing its icons.

## Files

| file | what it is |
| --- | --- |
| `gmailify.css` | source of truth — plain CSS, edit this |
| `gmailify.user.css` | generated, committed — the installable style |
| `gmailify.local.user.css` | generated, gitignored — your build, with photo and Google Sans |
| `fonts.css` | generated: Google Sans + Roboto as base64 `@font-face` (`./fonts.sh`) |
| `CLAUDE.md` | agent-facing notes: install, hooks, and the rules not to break |
| `build.sh` | regenerates `gmailify.user.css` (fonts.css + gmailify.css) |
| `fonts.sh` | re-downloads the latin subsets and rebuilds `fonts.css` |
| `background.css` | generated: background photo as a data URI (`./background.sh img.jpg`) |
| `background.sh` | downscales an image and embeds it as `--gm-bg-image` |
| `inspect.js` | DevTools helper for finding/repairing selectors |

Edit `gmailify.css`, run `./build.sh`, reimport in Stylus.

## Tuning it

Colors and metrics are CSS variables at the top of `gmailify.css` (`--gm-bg`,
`--gm-row-height`, `--gm-compose`, …). Change those before touching selectors —
most look changes don't need any new rules.

Knobs added for list density and search shape:

| variable | does |
| --- | --- |
| `--gm-row-font` | message list text size (14px = Gmail) |
| `--gm-row-line` | line height — the real lever on row height |
| `--gm-row-pad-y` | vertical padding inside a row |
| `--gm-nav-width` | folder pane width; aligns the search field's left edge to the list |
| `--gm-search-height` / `--gm-search-radius` | search pill size and roundness |

Background and translucency:

| variable | does |
| --- | --- |
| `--gm-bg-image` | the image behind everything; ships as a gradient |
| `--gm-pane` | list / reading pane veil — lower alpha shows more background |
| `--gm-row-read` / `--gm-row-unread` | row translucency, read vs unread |

To use your own photo:

```sh
./background.sh ~/Pictures/photo.jpg   # downscales, embeds, rewrites background.css
./build.sh
```

A web page cannot load `file://` images, which is why it has to be inlined
rather than referenced.

Fonts are the real ones Gmail uses — Google Sans for chrome, Roboto for message
text — embedded as data URIs in `fonts.css`. They are deliberately not
`@import`-ed from fonts.googleapis.com: an extension's injected stylesheet is
still bound by the page's CSP, so a remote font can be blocked with no error
and leave you in Helvetica. That embedding is why the built file is ~320KB.

CSS cannot turn Outlook's three-line row into Gmail's one-line row — the lines
are separate elements. For a genuinely short row, set **Settings → Mail →
Layout → Message preview: off** and **Message spacing: Compact** in Outlook
itself, then let this stylesheet handle the look.

Font is swapped through Fluent's `--fontFamilyBase`, never through element
selectors — see the warning comment in §2 before adding any `font-family` rule.

The single highest-leverage block is **§1 fluent**: OWA is built on Fluent UI v9,
so remapping `--colorNeutralBackground1`, `--colorBrandBackground` and friends
recolors most of the app in one move. The later sections only handle what the
design tokens can't express (shape, density, hiding chrome).

## When an OWA update breaks it

OWA's class names are hashed (`fui-Button`, `___1m2vxyz`) and churn between
builds, so every rule here hangs off attributes Microsoft keeps stable:
`data-app-section`, `role`, `aria-label`, and a few ids. Those are steadier, but
not guaranteed — expect occasional repair.

To repair: open Outlook, paste `inspect.js` into the DevTools console, then

* `gmailify.check()` — which selectors still match and which are dead
* `gmailify.hooks()` — every `data-app-section` / `role` / `aria-label` on the
  page, ranked, to pick a replacement hook
* `gmailify.at()` — ancestry of the element selected in the Elements panel
* `gmailify.rail()` — locates the left app rail and prints selectors for it
* `gmailify.row()` — full skeleton of one message-list row: roles, heights,
  padding, line-height, so density work stops being guesswork
* `gmailify.tokens()` — the Fluent variables this build actually reads

Prefer a new attribute-based selector over a hashed class, even a clumsy one.

## Where the numbers come from

The palette, densities and row model are lifted from Gmail's own stylesheet —
save a Gmail inbox with **File → Save Page As → Complete**, and the rules are in
the inline `<style>` blocks of the saved HTML. The ones that matter:

```css
.bkK>.nH { background-color: rgba(255,255,255,0.8); border-radius: 16px }
.zA      { padding: 4px 0; box-shadow: inset 0 -1px 0 0 rgba(100,121,143,0.12) }
.yO      { background: rgba(0,0,0,0.09) }   /* read   */
.zE      { background: none }               /* unread */
.x7      { background: #c2dbff }            /* selected */
.zA:hover{ box-shadow: inset 1px 0 0 #dadce0, …; z-index: 2 }
.y2      { color: rgb(95,99,104) }          /* snippet */
.xY      { height: 20px; font-size: .875rem }
```

Note the row model, which is not what you would guess: the **pane** holds the
white veil, unread rows are **fully transparent** so they show it at full
strength, and read rows are knocked back with a **black** overlay rather than a
weaker white one. Hover changes no background at all.

## Outlook's side, from a saved page

Save Outlook with **File → Save Page As → Complete** and the real hooks are in
the HTML and the `owa.*.css` bundles. What that settled, after several rounds of
guessing had failed:

* **Folders** carry `data-folder-name="inbox"` — a clean lowercase name. Their
  `title` is `"Inbox - 1,903 items (1,162 unread)"`, so exact-match selectors on
  `title` never fire. The glyph is a pair of `<i class="fui-Icon-font">`
  elements (filled + regular).
* **Message rows** are `div[role="option"][data-convid]`, not a grid of
  `role="row"` — there are 71 options on a loaded page and no message rows.
* **The background** has its own layer: a bare `<div>` in `#app` with an inline
  `background-image` (Outlook's own theme photo), `background-attachment:fixed`,
  `z-index:-1`. It sits above the `<body>` background, so painting body does
  nothing visible. Paint that div instead.
* **Opaque white** comes mostly from OWA's own variables, not Fluent's:
  `--neutralPrimarySurface` (291 references) and `--neutralSecondarySurface`
  (63). Remapping those two does more than any selector.
* **`data-app-section` has exactly six values** in a loaded mailbox:
  `MessageList`, `NavigationPane`, `Ribbon`, `NotificationPane`,
  `UpsellBannerSection`, `CopilotDabRibbon`. `FolderPaneContainer`, `AppBar`,
  `LeftRail`, `BriefingBanner`, `AdsRegion`, `MyDayPane` and the rest were
  invented — they never matched anything.
* The folder pane is `[data-app-section="NavigationPane"]`. `role="navigation"`
  is the left **app rail** (`aria-label="left-rail-appbar"`), a different thing.
* The message list is `[role="complementary"][aria-label="Message list"]`, but
  the reading pane is `[role="main"][aria-label="Reading Pane"]` — different
  landmark types, so a rule written for one silently misses the other. With a
  message open, `data-app-section` also gains `ConversationContainer` and
  `MailReadCompose`, and `#ReadingPaneContainerId` exists.
* The reply bar at the foot of a message is `[aria-label="Quick actions"]`.
* Panes stack veils. The title box and the message card are both `.WWy1F`,
  i.e. `background-color: var(--neutralPrimarySurface)`. Scope that variable to
  `transparent` on the pane and let the pane paint once, rather than clearing
  each box.
* Acrylic, not containers, is what makes surfaces white:
  `.GciPK { backdrop-filter: blur(24px); background-color: var(--whiteTranslucent65) }`.
  The `--whiteTranslucent40/50/65/70` family is used only by those surfaces.

When checking a saved page, strip the `<style>` blocks first — Stylus's injected
CSS is saved with the page, so grepping the raw HTML finds your own selectors
and reports them as if they were Outlook's.

## Performance: do not sweep the tree with :has()

Earlier versions cleared container backgrounds with

```css
body *:has(div[role="option"]) { background-color: transparent !important }
```

which made Outlook flicker continuously. The message list is virtualised, so
rows are created and destroyed as you scroll, and each mutation forces the
browser to re-test whether **every element on the page** still matches. That is
a permanent style-recalculation loop.

It was also unnecessary: those containers were not painting anything themselves,
they were reading OWA's surface variables. **Fix the variable, never sweep the
tree.** `:has()` is fine with a narrow subject over a static subtree — the
folder list, one known container — and never with `body *`.

The same rule applies to size. The message list is **windowed**: it decides how
many rows fit, renders that many, measures, and adjusts. A `height`,
`min-height`, `padding`, `line-height` or `font-size` set on a row from outside
makes the measurement disagree with the layout on every pass, so it keeps adding
and removing rows — they blink in and out. Outlook exposes the geometry it reads:

```css
--condensedRowMinHeight     /* 40px default; Gmail is ~28 */
--firstRowHeight            /* 20px — already Gmail's .xY */
--firstRowVerticalPadding   /* 4px — already Gmail's .zA */
--condensedRowPaddingBottom
```

Set those. Never set height or padding on `div[role="option"]`.

## Status

v0.1.0, first pass. The selectors are built from OWA's documented-stable
attribute hooks and have **not** yet been verified against a live signed-in
session — run `gmailify.check()` and fix what it reports dead. Pieces most
likely to need adjustment: unread-row detection (§5), the ribbon's current
container (§7), and the Copilot / right-rail nodes (§8), all of which Microsoft
has moved before.
