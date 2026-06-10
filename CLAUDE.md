# CLAUDE.md — Catena

Guidance for working in this repo. Read this first; it captures hard-won domain
knowledge that isn't obvious from the code alone.

## What this is

**Catena** visualizes the *web of tradition* — the connected net of citations
within papal encyclicals, and the councils, saints, and scripture they draw upon.
A Python pipeline scrapes encyclicals, parses their footnotes into a deduplicated
citation graph, precomputes a force-directed layout, and emits one static JSON
file; a dependency-free static site renders it as an interactive "constellation".

The name nods to the *Catena Aurea* (Aquinas's "golden chain" of patristic
citations) — that's the conceptual model and the visual metaphor.

**Repo facts:** renamed from "Ex Cathedra" → remote is
`github.com/jkeuhlen/catena`, but the **local dir is still `workspace/ex-cathedra`**.
The CLI command and package dist name are `catena`; the Python package *directory*
is `pipeline/`. Hosting target: Cloudflare + custom domain (not yet deployed).

## Commands (Makefile — run `make` for the list)

```
make build     # fetch → parse → build graph (writes data/graph/graph.json + site/data/graph.json)
make run       # serve the static site at http://localhost:8000  (PORT=8000)
make test      # pytest
make lint      # ruff (Python) + node --check on site/app.js
make fmt       # ruff format + safe fixes
make check     # lint + test  (run before committing)
make preview   # regenerate docs/preview.png via headless Chrome
make clean     # remove caches + fetched HTML (keeps the built graph)
```

`uv` manages Python (≥3.11); `uv run` auto-syncs, so no separate install is needed.
Add an encyclical: append its URL to `SEEDS` in `pipeline/cli.py`, then `make build`.

## Architecture

```
pipeline/
  fetch.py      polite, on-disk-cached HTTP (data/raw/, 1 req/s, real UA)
  parse.py      Vatican HTML → ParsedDocument (metadata + Citations + scripture)
  normalize.py  author / type / document-identity / name-casing normalization
  works.py      curated canonicalization of famous classical/patristic works
  bodies.py     curated curia / council / dicastery URL-slug → author name
  pontiffs.py   curated pope records (slug, ordinal, reign, profile URLs)
  lifespans.py  curated temporal spans for council & saint author nodes
                (dates for the Timeline ribbon gutter; popes come from pontiffs)
  scripture.py  biblical citation parsing (Catholic 73-book canon)
  graph.py      ParsedDocuments → deduplicated {nodes, edges, meta}
  layout.py     force-directed layout precompute (networkx spring_layout)
  cli.py        fetch / parse / build commands; SEEDS list; depth-1 crawl
site/
  index.html, styles.css, app.js   static canvas renderer (no graph library)
  about.html                       project + "how to read it" page
  data/graph.json                  build output consumed by the site
tests/          pytest for the pure parsing/graph logic
data/graph/     committed build output;  data/raw|parsed/  gitignored
```

### Data model

Node types: `document` (a work), `author` (person/council/dicastery), `scripture`
(a passage). Edge types: `cites` (doc→doc), `authored_by` (doc→author),
`cites_scripture` (doc→passage). Node fields include `degree` (for sizing) and
`x`/`y` (precomputed layout). Categories used by the legend filter:
`source` = `is_source` docs, `document` = other docs, plus `author`, `scripture`.

**Canonical identity** of a document = its vatican.va URL slug with the language
suffix stripped (`vat-ii_const_19651207_gaudium-et-spes` for any edition). This is
why every language version collapses to one node. Text-only citations dedupe onto
URL-backed nodes by normalized title (`graph.py`).

## Domain knowledge & parsing rules (the important part)

Vatican pages are Word HTML exports. Footnotes are the data; the markup is messy
and varies by era. Key facts learned the hard way:

- **Notes come in three eras** (`_collect_notes` picks the scheme):
  - **Modern (anchored)**: `<p>` blocks each containing a back-link anchor
    `<a name="_ftnN" href="#_ftnrefN">`. Older pages add `class="MsoFootnoteText"`;
    Francis-era pages use a bare `<p>`. **Select by the anchor, not the class.**
    Benedict/JP2 *endnotes* are identical but with the `_edn`/`_ednref` prefix.
  - **Pre-2000 (anchorless)**: Leo XIII → John Paul II ship notes as plain text
    after a single `<hr>`, in a marker zoo — `(N)`, `N).`, bare `N.`, `N .`
    crammed into one `<p>`, or a defunct `<a name="$N">` bookmark (the `$` is
    URL-encoded `%24`, the counter is non-decimal & its link text is unreliable).
    `_legacy_notes` ignores all that and **splits the post-`<hr>` region on the
    ascending note numbers** — the one signal common to every era. A marker is a
    number at a block boundary (start of `<p>`/after `<br>`) or one with a space
    before its `.`/`)` ("22." with no space is a *locator*, not a marker). It
    tolerates a stray leading section number ("14. (6)…", Populorum). The bare
    number and its punctuation are often separate elements, so the per-note text
    can start with an orphan ". "/") " — stripped in `_parse_note`.
  - Scripture-only notes ("Cf. *Gen* 1:28") must **not** become works: an
    italicized book sigil is rejected via `scripture.is_book` in `_first_title`.
- **Author lives *before the first link*.** When a footnote links to a work, the
  link text is the title, so the author is whatever text precedes that link
  (often nothing). Parsing author from the whole footnote text was the source of
  many bugs. For link-less footnotes, author = text up to the first type keyword,
  else up to the first comma/colon.
- **Type-leading titles have no author.** "Encyclical Letter *Laudato Si'*…" or
  "Address to…" at the start → author `None`, type inferred from the title.
- **Apparatus is never an author.** Strip leading `cf.`/`cfr.`/`see` (incl.
  no-space "Cf.Pontifical"), leading quoted phrases (`"…", Aristotle, Politics`),
  and resolve `ibid.` (same work → inherit full target) vs `idem`/`id.` (same
  author → inherit author only). See `_clean_lead`, `_IBID_LEAD`, `_IDEM_LEAD`.
- **Malformed markers**: the source sometimes drops a bracket ("185]"); strip the
  leading marker using the *known* footnote number (`_strip_marker`).
- **Metadata**: `<title>` formats differ across eras; document type often comes
  from the meta `description` (title-cased, since it may be ALL-CAPS). The
  `_meta_content` helper takes `**attrs` — call it `_meta_content(soup, name="…")`,
  not `attrs={...}`.
- **Detection is case-sensitive on purpose.** Scripture book abbreviations and
  type phrases are matched case-sensitively so "Is"/"Am"/"Job"/"letter" in prose
  don't false-match. The description fallback title-cases first.
- **Author display casing**: `normalize.recase_name` title-cases SHOUTING names
  ("PAUL RICOEUR" → "Paul Ricoeur") while preserving mixed-case, particles ("de"),
  roman numerals ("XVI"), initials ("J.R.R."), accents, and hyphens. Keys are
  lowercased so casing never causes duplicate nodes.

### Curated work mappings (`works.py`)

Classical/patristic works (the *Summa*, *Confessions*, *City of God*, Chrysostom's
homilies…) are cited inconsistently and often without an author, so the generic
parser scatters them into mis-attributed nodes. `works.py` is a **curated table**
mapping a normalized-title substring → canonical (title, author, stable key). This
is the intended extension point: when a new famous work surfaces mis-attributed,
add one line to `_WORKS_RAW`. Applied per-citation in `parse_document` via
`_canonicalize`.

When adding encyclicals, expect new mis-parses — run a scan of author-node labels
for apparatus tokens / titles-as-authors / ALL-CAPS, and decide between a general
parser fix vs. a `works.py` entry.

## Frontend (site/)

Vanilla HTML/CSS/JS, no framework, no graph library — the layout is precomputed so
`app.js` just draws static coordinates on a `<canvas>` with a small camera
(pan/zoom), hover tracing, multi-select, and legend filters. Aesthetic:
illuminated manuscript — gold leaf / lapis / oxblood on aged-ink; Cormorant
Garamond + EB Garamond. Interactions: click pins a node (multi-select; 2+ reveals
bridge nodes), search (`/`) flies to a node, legend swatches filter by category,
Esc clears.

**Timeline view** (`#view=timeline`) lays documents on a chronological y-axis
(year) with a beeswarm x-spread. Two deliberate departures from Explore: (1)
**dots are uniform** — degree-sizing is suppressed in any non-Explore view
(`radius()` short-circuits) because position, not size, carries the meaning;
(2) a **right-edge "ribbon gutter"** paints dated author context — pope reigns,
councils, and saint lifetimes — as vertical bands clamped to the axis, sourced
from each author node's `span` field (`graph.finalize`, from `pontiffs`/
`lifespans`). Bands are screen-pinned (like the year axis), lane-packed per kind
(reign/life/council zones, edge→swarm), deduped across the fragmented council
author keys, and clickable (pins the author node → lights the encyclicals citing
it). Figures whose whole span predates the axis window (most Fathers) collect
into an "earlier" stack at the top of the gutter. To add/fix a date, edit
`pipeline/lifespans.py` (the curated extension point) and `make build`.

**CSS gotcha (bitten 3×):** a class with an explicit `display` beats the `[hidden]`
attribute's `display:none`. Any element toggled via `el.hidden = true` that also
has a `.class { display: … }` needs an explicit `.class[hidden] { display: none }`
(see `.detail__link`, `.selection`).

## Layer-2 crawl (depth-1 recursion)

`make build` parses the 16 seeds and then **recursively parses every cited
document** that passes a kind filter — encyclicals, apostolic exhortations,
apostolic letters, and everything under `/roman_curia/` and
`/archive/hist_councils/` (`pipeline.cli._is_layer2_candidate`). Speeches /
homilies / messages / audiences / angelus are deliberately excluded: they'd add
leaf nodes without enriching edge structure. Layer-2 dedups by canonical
`doc_key` (not URL) so the same work cited with many fragment anchors is
fetched once. Pass `--no-recurse` to skip the crawl.

Layer-2 docs get `in_corpus=True, is_source=False`; seeds get
`in_corpus=True, is_source=True`. The legend filters on `is_source`.

Four eras of footnote markup are now handled — see ``_collect_notes`` in
``parse.py``. Strategies are tried in this order; the first non-empty result
wins:

1. **Modern anchors** (``_anchor_notes``): ``<a name="_ftnN"/_ednN"/>`` with a
   back-link href ending or containing ``#_ftnrefN`` / ``#_ednrefN``. Covers
   most pages from JP2 onwards, including absolute-href shapes (Evangelii
   Gaudium, w2.vatican.va).
2. **Vatican II / section-restarting** (``_section_notes``): a ``<p>NOTES</p>``
   header followed by one ``<p>`` per note with the number leading the
   paragraph; numbering resets at every chapter ("Preface 1, 2; Introduction
   1, 2; Chapter I 1, … 16"). The discriminator that distinguishes this from
   spurious matches inside a pre-2000 doc (which often also has a centered
   ``<p>NOTES</p>``): **the first matched note must be number 1**. Pre-2000
   notes are crammed into one ``<p>`` with ``(N)`` markers, so any
   leading-digit ``<p>`` tags after their NOTES heading are stray body
   locators ("14)", "23)") — never first-of-section.
3. **Bracket-numbered, one-per-paragraph** (``_bracket_notes``): a long
   contiguous run of ``<p>[N] …</p>`` tags with no anchors, no ``NOTES``
   header, no ``<hr>`` boundary — just a tail-of-file note dump. The
   Compendium of the Social Doctrine of the Church uses this shape for its
   1232 notes. Discriminator: at least 20 such paragraphs in monotonically
   non-decreasing order (stray inline ``[N]`` quotations or back-links in
   body prose never accumulate to that depth).
4. **Pre-2000 legacy split** (``_legacy_notes``): anchorless plain-text notes
   in the post-``<hr>`` region with a marker zoo (``(N)``, ``N).``, ``N.``,
   ``N .``), split on the monotonically ascending note numbers.

Lumen Gentium and Apostolicam Actuositatem parse correctly but contribute 0
work-citations because their footnotes are *almost entirely scripture*
("1 Cf. Mk. 16:15; 2 Col. 1:15; …"); those refs land in the document-wide
scripture sweep instead. All five Vatican II seeds and both pontifical-council
documents (Compendium, Erga Migrantes) are now properly woven into the graph
— none of the original "layer-2 sinks" remain.

## Catechism handling

The Catechism of the Catholic Church is served as five deep-linked HTML pages
(`/archive/ENG0015/__P*.HTM`) — one per part, plus the index. All five collapse
onto the single canonical key `doc:catechism-of-the-catholic-church` in
`normalize.doc_key_from_url`, and `works.py` attaches the curated
(`Catholic Church`, `Catechism`) author/type so the merged node never picks up
a stale label from whichever citation registered it first.

## Testing & verification

- `make check` before committing. Tests live in `tests/` and cover the pure
  parsing/graph/normalize logic with small inline HTML fixtures (no network).
- **Regression net for the seed corpus**: `tests/regression/seed_snapshot.json`
  pins every seed's parsed shape (all citation tuples, author histogram,
  scripture histogram). The pytest in `tests/regression/test_seed_regression.py`
  re-parses from `data/raw/` and diffs against the snapshot — any drift fails.
  Regenerate intentionally with `uv run python -m tests.regression.snapshot`
  and commit the diff alongside the code change.
- **Visual verification** uses headless Chrome:
  `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless
  --screenshot=out.png --window-size=1500,950 --virtual-time-budget=3500 URL`.
  To screenshot a specific interaction, temporarily patch `app.js` after
  `bindEvents()` to call the relevant function, screenshot, then restore. `make
  preview` does this to regenerate `docs/preview.png`; it serves with
  `--directory site` and cleans up the server.

## Known limitations / roadmap

- **Two-generation graph**: seeds + one layer of cited documents are parsed
  (see "Layer-2 crawl" above). Going to depth-2 would 10× the corpus and
  needs a generation cap + bandwidth/storage plan before it's worth doing.
- **Multi-citation footnotes**: a footnote citing several works attributes them
  all to the first author (real authorship is recovered when a work is parsed
  directly or via `works.py`). In the anchorless legacy notes this also leaves
  some apparatus tails as authors ("…AAS 60 (1968), 485-487; Benedict XVI").
- **Prose-prefixed footnotes** (e.g. "In these considerations… cf. X") and exotic
  citations (a film) can still mis-parse — rare, peripheral, left as-is.
- **Under-attributed patristic works** in legacy notes cited with no author and
  only a Latin sigil + PG/CCL locator ("In Matthaeum", "In Epistulam ad Romanos")
  surface as their own title-as-author nodes; attribute the famous ones case by
  case in `works.py` (needs the PG/source number to be sure — don't guess).
- All recognised layer-2 documents now parse (Vatican II, curia documents,
  Compendium); the four-era parser is documented in "Layer-2 crawl" above.
- The build needs **scipy** (`networkx.spring_layout` switches to a sparse solver
  above ~500 nodes). `compute_layout` runs ~30 s at ~1.9k nodes and ~2–3 min
  at ~5k nodes (build-time only); lower `iterations` in `layout.py` if painful.
- Not yet: papalencyclicals.net adapter for older texts; graph analytics
  (centrality/lineage); per-document pages; Cloudflare deploy.

## Conventions

- Match the surrounding code's style and comment density. Keep the browser
  dependency-free and the site fast (precompute over runtime libraries).
- Commit/push only when asked; end commit messages with the Co-Authored-By line.
- There is also a persistent memory at the path in the system prompt; `CLAUDE.md`
  is the source of truth for project facts.
