# Blue sky

Unscheduled work, kept out of PLAN.md so the plan stays a list of things that will happen. Everything here is gated on someone upstream, missing a technical pathway, or waiting for a user to ask. An item graduates into PLAN.md when its gate lifts, with the reasoning recorded here so it does not have to be rebuilt.

Settled decisions and the measurements behind them are in [DESIGN.md](./DESIGN.md).

## Upstream asks

- A `# file:` pragma for Python type checkers, the equivalent of Go's `//line` directive, which is how templ reports template-native paths. With it, a generated stub could name its template and every checker would print `templates/profile.jinja:5:18` with nothing in between; `remap` and the editor mirror exist only because this is missing. ty is the best first target (pre-1.0, diagnostics still moving, small surface to change), pyright and mypy after a reference implementation exists. Do not block anything on it.
- Native type syntax in Jinja itself (rung 3 of the declaration rungs in [DESIGN.md](./DESIGN.md)). Belongs to Pallets, who move on evidence we generate at rungs 1 and 2. The Python parallel is `# type:` comments (PEP 484) proving demand for annotation syntax (PEP 526). The ask is worth making once real projects carry `{#def #}` headers in anger.

## Waiting on demand

- Extension-tag declaration (rung 2): `{% types user: User %}` through a registered Jinja Extension. Strictly worse coupling than the comment header until an editor or formatter treats comments badly enough to justify it.
- Framework adapters (Flask, FastAPI, django-jinja) that locate "this view renders this template with this context" and check the call site without a generated wrapper. No general pathway: render calls are dynamic, and each framework hides the context assembly differently. The wrapper covers the same ground today for anyone willing to call a generated function.
- Sidecar or registry binding as an alternative to the in-template header. The yak-shears migration showed the header suffices, so this waits for a repo that cannot annotate its templates (vendored templates, generated files).
- Argument-level filter signatures and a catalog for third-party filters. Return types are pinned for built-ins; argument types stay `Any` because a catalog that guesses reports errors on correct templates, and a third-party catalog is a maintenance treadmill with no owner. A pathway would need filter authors shipping their own signatures, which is an ecosystem ask, not a code change.
- A second Python-hosted template engine. Needs an engine-neutral IR between parser and emitter, covering the dozen node kinds `_emit_node` switches on (a few hundred lines, per the scope boundary in [DESIGN.md](./DESIGN.md)). Do it when a second engine has a user asking.

## Missing a pathway

- Editor mirroring for VS Code, Cursor, Zed, and Helix. Mirroring has to live client-side, because one language server cannot read another server's diagnostics, so each editor needs the same layer written against its own diagnostic API (`languages.onDidChangeDiagnostics` for VS Code). `editors/nvim/lua/types_for_jinja/mirror.lua` is the reference: ask the server which stub a template generates, load it hidden so the Python server checks it, then republish through the `types-for-jinja/remap` request. Waiting on someone who uses those editors, since an unverified extension is worse than none.
- Attribute completion through a parenthesised or filtered base (`(items | first).`). The cursor context is detected correctly, but the fragment has to be transpiled to Python before a language server sees it, and the probe truncates at the cursor rather than parsing the partial expression.
- Project-defined Jinja extensions, beyond the stock ones the `extensions` setting will cover. Loading arbitrary project code into the parsing Environment crosses the static-only line, and a custom tag's semantics are not inferable from its parser hook.

## Considered, no committed pathway

- Content-hash manifest so `generate` skips re-transpiling unchanged templates. The hash must cover the resolved base and imported template contents, because `extends` and `import` are inlined at transpile time, so a child stub changes when its parent does. Worth it only once template counts make generation itself noticeable; today the checker dominates.
- `TypedEnvironment(jinja2.Environment)`, the second Level 2 delivery option in [DESIGN.md](./DESIGN.md): `.render()` reads the header, validates the context, then delegates to Jinja. The decorated-wrapper route shipped and covers the need. This stays as the shape runtime enforcement would take without codegen.
- Templates behind a `DictLoader` or a database. There are no files to read, so checking them means executing the project to extract them, which crosses the static-only line. A project-side export step (write the templates to disk, point `generate` at them) is the workaround and may be the answer.
