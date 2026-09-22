// ================================================================
//  Layout library for redpen-generated quizzes.
//
//  One library, two documents: the blank quiz the students write on and the
//  red answer key.  `key: true` switches between them, and *nothing else*
//  differs -- the worked solutions are `place`d out of the flow, so they
//  occupy no layout space and every answer box on the key lands on exactly
//  the same page coordinate as on the blank.  `redpen build` checks that,
//  comparing the zone geometry harvested from both compiles.
//
//  That invariant is the whole reason the key can be trusted: zones are cut
//  from the blank, and a key whose boxes had drifted would quietly mis-crop
//  every scan.
// ================================================================

#let key-red = rgb("#c00000")

// How far a problem's body hangs in from its number, and so how far each
// sub-part is indented.  One constant, because the two must agree.
#let INDENT = 1.6em

// ---- Accessibility ------------------------------------------------
// Alt text so screen readers announce a spoken reading of the maths, and
// PDF checkers see a described Formula.
#let ieq(alt, body) = math.equation(alt: alt, body)
#let beq(alt, body) = math.equation(block: true, alt: alt, body)
#let mss = ieq("meters per second squared", $"m/s"^2$)

// ---- Zone geometry ------------------------------------------------
// Dropped at the top-left of an answer box, this reports where that box
// landed -- as fractions of the page, origin top-left, which is exactly the
// rectangle format redpen's config wants.  `typst eval` harvests them:
//
//   typst eval 'query(<zone>).map(it => it.value)' --in quiz.typ --format json
//
// The box's own width and height are passed in rather than measured: they
// are what we asked for, and `to-absolute()` resolves em to points inside
// the context where the text size is known.
// `grow-top`/`grow-bottom` widen the reported rectangle beyond the drawn box
// without moving the box itself.  The name line needs it: what is written
// sits *above* its rule, so a crop of the rule alone would catch nothing.
#let zone-mark(id, w, h, kind: "answer", grow-top: 0pt, grow-bottom: 0pt) = context {
  let p = here().position()
  let gt = grow-top.to-absolute()
  let gb = grow-bottom.to-absolute()
  [#metadata((
    id: id, kind: kind, page: p.page,
    x: p.x / page.width, y: (p.y - gt) / page.height,
    w: w.to-absolute() / page.width,
    h: (h.to-absolute() + gt + gb) / page.height,
  )) <zone>]
}

// Where a sub-part begins, so `redpen build` can tell whether the worked
// solution placed above it has room before the next one starts.
#let part-mark(id) = context {
  let p = here().position()
  [#metadata((id: id, page: p.page, y: p.y / page.height)) <partpos>]
}

// ---- The answer box -----------------------------------------------
// `label` names the quantity asked for, set in small grey type just past the
// box's right edge.  It is `place`d, so it hangs in the margin without taking
// any width -- the box keeps its full size and its flush-right position.
#let answer-box(b, key) = {
  let w = b.at("w", default: 3.4cm)
  let h = b.at("h", default: 1.9em)
  let tall = b.at("tall", default: false)
  let tag = place(
    (if tall { top } else { horizon }) + left, dx: 100% + 0.4em,
    text(size: 8pt, fill: luma(120))[#b.label],
  )
  box(width: w, height: h, stroke: 0.6pt, {
    place(top + left, zone-mark(b.id, w, h, kind: b.at("kind", default: "answer")))
    tag
    if key and b.at("answer", default: none) != none {
      align(center + horizon, text(fill: key-red, size: 9.5pt, weight: "bold",
        b.answer))
    }
  })
}

// ---- The worked solution ------------------------------------------
// Placed out of the flow, so the key's layout is the blank's.  Its height is
// reported alongside its position; `redpen build` compares that against the
// room actually left below, and warns when a solution would run into the
// next sub-part rather than letting it silently overprint.
// `place` with no alignment floats at the *current* position in the flow --
// just under the question -- while still taking no space.  Anchoring it to
// `top + left` instead pins it to the grid cell's corner, where it overprints
// the question and reports a position the overflow check cannot use.
#let work(id, body) = place(dy: 0.55em, layout(avail => context {
  // Everything here sits inside the `place`, including the measurement: a
  // bare `layout` is a block-level element and nudged the flow by ~0.007 of
  // the page, which is exactly the silent drift this design exists to avoid.
  //
  // Measured against the column it actually occupies, because `measure` on a
  // `width: 100%` block has no container to resolve against and comes back
  // with a nonsense height, which would make the overflow check lie.
  let content = block(width: avail.width, inset: (left: 1.1em),
    text(fill: key-red, size: 9.5pt, body))
  let m = measure(content)
  let p = here().position()
  [#metadata((
    id: id, page: p.page,
    y: p.y / page.height, h: m.height / page.height,
  )) <work>]
  content
}))

// ---- One sub-part -------------------------------------------------
// The question on the left, its answer boxes stacked on the right.
// `lbl` of `none` drops the (a) -- a problem that just asks for an answer has
// nothing to letter, and its body is the problem statement itself.
#let part(lbl, boxes: (), key: false, solution: none, id: "", body) = {
  let tall = boxes.any(b => b.at("tall", default: false))
  let w = boxes.at(0).at("w", default: 3.4cm)
  block(above: 0.7em, below: 0.6em, width: 100%, inset: (left: INDENT),
    grid(
      columns: (1fr, w), column-gutter: 0.8em,
      align: (left, if tall { top } else { bottom }),
      {
        part-mark(id)
        if lbl == none { body } else { [(#lbl) #body] }
        if key and solution != none { work(id, solution) }
      },
      stack(dir: ttb, spacing: 0.3em, ..boxes.map(b => answer-box(b, key))),
    ),
  )
}

// ---- A problem ----------------------------------------------------
// The number hangs in the left margin, as an enumeration would set it, but
// written out so a problem can be moved between pages without carrying enum
// state with it.
#let points(n) = text(size: 9.5pt, fill: luma(90))[#h(0.4em)\(#n points\)]

#let problem-head(n, title: none, pts: none, stem: none) = block(
  width: 100%, breakable: false, above: 0pt, below: 0.2em,
  grid(columns: (INDENT, 1fr), column-gutter: 0pt,
    [#part-mark("problem " + str(n))#n.], {
      if title != none { strong(title) }
      if pts != none { points(pts) }
      if stem != none { [\ #stem] }
    },
  ),
)

// ---- Page layout --------------------------------------------------
// One page's problems, and the single fractional-height region on that page.
//
// Exactly one: a `block(height: Xfr)` claims what is left of the page it
// starts on, so two of them put the second on a fresh page -- which is how
// one problem per page happened the first time this was written.  The
// writing room is therefore not owned by the problems but by the page, and
// shared out between sub-parts by the `v(g * 1fr)` spacers below.
#let quiz-page(body) = block(width: 100%, height: 1fr, body)

// A problem: its heading, then its sub-parts, each followed by the room a
// student writes in.  `gaps` weights that room -- it comes from the marks, so
// a sub-part worth twice as much gets twice the space to work in.
#let problem(n, title: none, pts: none, stem: none, parts: (), gaps: none) = {
  problem-head(n, title: title, pts: pts, stem: stem)
  let gs = if gaps == none { parts.map(_ => 1.0) } else { gaps }
  parts.zip(gs).map(((it, g)) => it + v(g * 1fr)).join()
}

// ---- Document setup -----------------------------------------------
#let name-line = align(right)[
  Name: #box(width: 7cm, height: 1em, stroke: (bottom: 0.5pt),
    place(top + left, zone-mark("name", 7cm, 1em, kind: "name",
      grow-top: 1.2em, grow-bottom: 0.15em)))
]

#let quiz-doc(title: none, key: false, note: none, body) = {
  set document(title: if key { title + " — Answer Key" } else { title },
               author: "Philip Chang")
  set page(
    paper: "us-letter",
    margin: (top: 0.7in, bottom: 0.55in, x: 0.85in),
    numbering: "1",
    // The name line rides in the header so it appears on every page; on the
    // key the ANSWER KEY flag joins it there, where it cannot disturb the
    // body layout and so cannot move a single answer box.
    header: if key {
      grid(columns: (1fr, auto), align: (left + bottom, right),
        text(fill: key-red, weight: "bold", size: 10pt)[ANSWER KEY], name-line)
    } else { name-line },
    header-ascent: 0.25in,
  )
  set text(size: 10.5pt)
  set par(justify: true, leading: 0.62em)
  set heading(numbering: none)
  show heading.where(level: 1): it => block(
    above: 0pt, below: 1.0em, width: 100%,
    align(center, text(size: 17pt, weight: "bold", it.body)),
  )

  [= #title]
  if note != none {
    block(width: 100%, inset: 6pt, stroke: 0.8pt, text(size: 9.5pt, emph(note)))
    v(0.4em)
  }
  body
}
