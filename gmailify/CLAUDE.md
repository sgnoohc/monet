# gmailify — notes for an agent

A Stylus userstyle that reskins Outlook Web (`outlook.cloud.microsoft`) to look
like Gmail. Read this before installing it, changing it, or debugging it.

## If the user asks you to install it on this machine

1. **Stylus must be installed in their browser.** It is a browser extension and
   you cannot install it for them — https://add0n.com/stylus.html (Chrome,
   Firefox, Edge). Ask them to confirm it is installed before going further.

2. **Point them at the install URL.** This is the whole install; nothing needs
   to be cloned, built, or copied:

   ```
   https://raw.githubusercontent.com/sgnoohc/monet/main/gmailify/gmailify.user.css
   ```

   Opening that URL in a browser with Stylus present shows an install page.
   `open -a "Google Chrome" <url>` works on macOS. They click **Install**.

3. **Optional, for the exact look in the screenshots.** The committed build
   falls back to Roboto and a gradient background, because Google Sans and the
   background photo are Google assets that should not be redistributed from a
   public repo. To restore them locally, from a clone:

   ```sh
   ./fonts.sh --google-sans                                   # Google Sans + Google Sans Text
   cp /path/to/any/photo.jpg background.jpg                   # any image they like
   LOCAL=1 ./build.sh gmailify.css gmailify.local.user.css
   ```

   The background is a drop-in: any `background.<ext>` in this directory (jpg,
   jpeg, png, heic, heif, webp, tif, tiff, gif, bmp) is downscaled and embedded
   by the `LOCAL=1` build, and re-embedded whenever it is newer than
   `background.css`. `./background.sh /path/to/img.jpg` still works for a file
   kept elsewhere. Only the `LOCAL=1` build embeds it — a plain `./build.sh`
   prints a note and leaves the committed style on its gradient.

   `--google-sans` writes `fonts.local.css` rather than `fonts.css`, so the two
   builds never overwrite each other. Then install `gmailify.local.user.css` by
   `file://` URL, which needs **Allow
   access to file URLs** enabled for Stylus at `chrome://extensions` → Stylus →
   Details. `background.<ext>`, `background.css` and `gmailify.local.user.css`
   are all gitignored.

4. **Verify** by asking them to reload Outlook: rounded translucent panes, a
   photo or gradient behind everything, white sidebar text with Gmail's folder
   icons, no ribbon.

## If you are changing the style

`gmailify.css` is the source. `./build.sh` regenerates `gmailify.user.css`
(fonts.css + gmailify.css, wrapped in the UserCSS metadata and `@-moz-document`
block). Never edit `gmailify.user.css` or `fonts.css` by hand — both are
generated. After a change the user must reinstall from the same URL and reload.

Nine rules, each of which was learned by breaking the app:

1. **Fix the variable, never sweep the tree.** OWA paints through its own
   variables — `--neutralPrimarySurface` (291 references), `--whiteTranslucent65`
   (the acrylic sidebar), `--headerBackground`, `--neutralLight`. Restyling
   through those beats any selector. A `body *:has(div[role="option"])` sweep
   made Outlook flicker permanently: the message list is virtualised, so every
   row mutation forced the browser to re-test the entire page.

2. **Never set `height`, `padding`, `line-height` or `font-size` on a message
   row.** The list measures rows to decide how many fit, so an override makes
   the measurement disagree with the layout and rows blink in and out. Outlook's
   **Settings → Mail → Layout → Message spacing** is the supported way to change
   density. Row geometry variables exist (`--condensedRowMinHeight`) but changing
   them desynchronises the same way.

3. **Never set `font-family` on an element selector.** Icons are private-use
   glyphs in an icon font carried by plain `<span>`/`<div>` nodes with hashed
   classes; any rule broad enough to restyle text also hits them and they become
   tofu boxes. The font swap goes through `--fontFamilyBase`. The one exception is
   the message body (§6): Gmail renders mail in **Arial**, not Roboto, so
   `--gm-font-body` goes on the body container itself and inherits down. Keep it
   that way — a `*` sweep inside the body would flatten every sender's own
   typeface and hit any glyph font inside the mail.

4. **Paint a veil once.** A pane, the box inside it and its toolbar all read the
   same surface variable, so leaving each painted stacks translucent layers and
   draws a lighter rectangle around the content. Paint on the region, and clear
   `--neutralPrimarySurface` on `[class*="fui-FluentProvider"]` elements inside
   it — Fluent providers re-declare every token locally and will otherwise
   reinstate it.

5. **`display: none` on a container the list measures brings the flicker back.**
   The message-list toolbar is deliberately left visible and styled to blend.

6. **Some of Outlook's chrome is not chrome.** The "You don't often get email
   from …" tip is injected by Exchange into the message HTML before it is
   sent, so it arrives as part of the mail — a `bgcolor="#EAEAEA"` table under
   `.infoBarDivClass`'s reach, wearing OWA's `revert !important` sanitiser
   styles and no Outlook attribute at all. Hooks for that class of thing come
   from the content: here, the `aka.ms/LearnAboutSenderIdentification` link.
   And keep `:has()` on such a rule anchored with child combinators —
   `table:has(a[href*=…])` matches every table the target is nested inside,
   which in a newsletter is the entire email.

7. **Suspect your own stylesheet before Outlook's.** The wide white rectangle
   with a shadow behind an attachment was §8's popup rule:
   `[role="listbox"]:not([aria-label^="Message list"])` paints every listbox
   `--gm-surface` with a drop shadow, to make menus opaque — and the
   attachment well is a `role="listbox"`. Same specificity as §6's reset and
   later in the file, so it won, and eight versions went into clearing fills
   off ancestors that were never drawing anything. When a reset with
   `!important` appears to do nothing, grep the file for other rules matching
   that element before reaching for a broader selector; the roles OWA reuses
   — `listbox`, `option`, `heading` — are where §5, §6 and §8 collide.

8. **`role="option"` is not only a message row.** Attachment tiles carry it
   too, so every unscoped `div[role="option"]` rule in §5 reaches them —
   `div[role="option"]:hover` was painting Gmail's row hover shadow onto each
   attachment, which was half of the box §6 now clears. Check the role before
   adding an unscoped rule there. And the tile is full-width, not a chip sized
   to its contents, so it gets no fill on hover, focus or selection either — a
   background there is a rounded slab across the whole pane.

9. **Never match a row on an aria-label *substring*.** A row's `aria-label` is
   its entire rendered content — sender, subject and preview snippet — so a
   selector like `[aria-label*="briefing" i]`, meant for a banner, also matched
   a message whose subject was "Daily Briefing" and hid it from the list. Only
   `^=` on the status words OWA puts first (`Unread`, `Flagged`) is safe; for
   anything else, name the element by `data-app-section` or `role`.

## Where the facts come from

Nothing here is guessed; both sides were read from saved pages
(**File → Save Page As → Complete**).

- **Gmail's values** — save a Gmail inbox; the rules are in the inline `<style>`
  blocks. `.bkK>.nH` (pane, `rgba(255,255,255,0.8)`), `.zA` (row padding and the
  inset-shadow divider), `.yO` (read rows — a *black* 9% overlay), `.zE`
  (unread — fully transparent), `.x7` (selected `#c2dbff`), `.y2` (snippet
  `rgb(95,99,104)`), `.xY` (20px cell, `.875rem`).
- **Outlook's hooks** — save an Outlook mailbox, once with a message open.
  **Strip the `<style>` blocks before grepping**: Stylus's injected CSS is saved
  with the page, so grepping raw HTML finds your own selectors and reports them
  as Outlook's. That mistake produced a list of `data-app-section` values that
  did not exist.

Verified hooks:

| thing | selector |
| --- | --- |
| message list pane | `[role="complementary"][aria-label="Message list"]` |
| reading pane | `[role="main"][aria-label="Reading Pane"]` (a *different* landmark) |
| message row | `div[role="option"][data-convid]`; unread → `[aria-label^="Unread"]` |
| folder | `[data-folder-name="inbox"]` (lowercase; `title` is `"Inbox - 1,903 items…"`) |
| folder pane | `[data-app-section="NavigationPane"]` |
| app rail | `[role="navigation"][aria-label="left-rail-appbar"]` |
| header | `#OwaTitleBar`; search `#searchBoxColumnContainerId`, `#topSearchInput` |
| reply bars | `[aria-label="Email message"] [class*="fui-Toolbar"]`, `[aria-label="Quick actions"]` |
| message body | `[id^="UniqueMessageBody"]`, `[aria-label="Message body"]`, `.allowTextSelection` (only one may exist per build) |
| message metadata | level-3 headings, ids `MSG_<convid>_FROM` / `_DATETIME` / `_SUBJECT`; the date also has `[data-testid="SentReceivedSavedTime"]` |
| info bars | `.infoBarDivClass`; retention is the `InfoFilled` one |
| first-contact tip | injected into the message HTML, not an info bar — only hook is `a[href*="LearnAboutSenderIdentification"]` |
| attachment tile | `[role="listbox"][aria-label="file attachments"] [role="option"]` — same role as a message row |

Real `data-app-section` values, complete: `MessageList`, `NavigationPane`,
`Ribbon`, `NotificationPane`, `UpsellBannerSection`, `CopilotDabRibbon`, and
with a message open `ConversationContainer`, `MailReadCompose`.

## Debugging

`inspect.js` is a console helper — paste the whole file into DevTools on
Outlook (`pbcopy < inspect.js`), then:

`gmailify.check()` which selectors still match · `gmailify.row()` a row's
skeleton with computed heights and fonts · `gmailify.date()` (message open)
the header's date nodes and the body container, with paste-ready selectors ·
`gmailify.opaque()` what is covering the background · `gmailify.panes()` the
offset between the two panes · `gmailify.rail()`, `gmailify.hooks()`,
`gmailify.tokens()`, `gmailify.at()`.

If a rule stops working after an Outlook update, re-derive it from a fresh saved
page rather than guessing — the class names are build hashes and change. The
only rules keyed to a hash are the subject box (`.NTPm6`), the subject pill
(`.MshDW`, `.mBy5m`) and the list preview text (`.ASFJj`); each says so in a
comment.

**`[role="heading"]` in the reading pane is not the subject — it is a whole
family.** Every field of a message's metadata is its own **level-3** heading,
with an id of the form `MSG_<convid>_<FIELD>`:

```html
<div data-testid="SentReceivedSavedTime" role="heading" aria-level="3"
     id="MSG_QAEIJBK8QAA_DATETIME">Thu 9/17/2026 2:52 PM</div>
<span class="Q84Kk YzEel s5zQy" role="heading" aria-level="3"
      id="MSG_QAEIJBdKwAA_FROM">… on behalf of …</span>
<div role="heading" aria-level="3" id="MSG_QAD/KIb6QAA_ATTACHMENTS">…</div>
```

**That id family is the best hook in the reading pane.** `_FROM`,
`_DATETIME`, `_SUBJECT`, `_ATTACHMENTS` — every metadata block has one, and
they survive builds where the classes do not. Reach for `[id$="_FIELD"]`
before `:has()` or a structural guess: the white card around the attachment
well was found by `:has()` twice, wrongly, when it was simply
`[id$="_ATTACHMENTS"]`, the listbox's own parent.

§6's subject rule — `font-size: 22px` on `[role="heading"]` — was sizing all
of them. It cost two rounds to find, because each field broke differently: the
date simply went 22px, while on the From line the sender chips set their own
size and only the bare `on behalf of` text node between them inherited it, so
one fragment of the line was giant.

The rule now excludes `[aria-level="3"]` wholesale and names the subject by
`[id$="_SUBJECT"]`, so a metadata field Outlook adds later joins the excluded
family instead of breaking. Suspect this rule for anything oversized in the
pane, and check the element for `role="heading"` before writing a new one.

`data-testid` is Outlook's one genuinely descriptive attribute — worth
grepping when `aria-label` and `data-app-section` come up empty.
