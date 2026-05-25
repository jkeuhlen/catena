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
  scripture.py  biblical citation parsing (Catholic 73-book canon)
  graph.py      ParsedDocuments → deduplicated {nodes, edges, meta}
  layout.py     force-directed layout precompute (networkx spring_layout)
  cli.py        fetch / parse / build commands; SEEDS list
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

- **Footnote bodies** are `<p>` blocks each containing a back-link anchor
  `<a name="_ftnN" href="#_ftnrefN">`. Older pages add `class="MsoFootnoteText"`;
  Francis-era pages use a bare `<p>`. **Select by the anchor, not the class.**
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

**CSS gotcha (bitten 3×):** a class with an explicit `display` beats the `[hidden]`
attribute's `display:none`. Any element toggled via `el.hidden = true` that also
has a `.class { display: … }` needs an explicit `.class[hidden] { display: none }`
(see `.detail__link`, `.selection`).

## Testing & verification

- `make check` before committing. Tests live in `tests/` and cover the pure
  parsing/graph/normalize logic with small inline HTML fixtures (no network).
- **Visual verification** uses headless Chrome:
  `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless
  --screenshot=out.png --window-size=1500,950 --virtual-time-budget=3500 URL`.
  To screenshot a specific interaction, temporarily patch `app.js` after
  `bindEvents()` to call the relevant function, screenshot, then restore. `make
  preview` does this to regenerate `docs/preview.png`; it serves with
  `--directory site` and cleans up the server.

## Known limitations / roadmap

- **Single-generation graph**: only the seed encyclicals are parsed; the works
  *they* cite aren't crawled recursively yet (the obvious next big feature).
- **Multi-citation footnotes**: a footnote citing several works attributes them
  all to the first author (real authorship is recovered when a work is parsed
  directly or via `works.py`).
- **Prose-prefixed footnotes** (e.g. "In these considerations… cf. X") and exotic
  citations (a film) can still mis-parse — rare, peripheral, left as-is.
- Not yet: papalencyclicals.net adapter for older texts; graph analytics
  (centrality/lineage); per-document pages; Cloudflare deploy.

## Conventions

- Match the surrounding code's style and comment density. Keep the browser
  dependency-free and the site fast (precompute over runtime libraries).
- Commit/push only when asked; end commit messages with the Co-Authored-By line.
- There is also a persistent memory at the path in the system prompt; `CLAUDE.md`
  is the source of truth for project facts.
