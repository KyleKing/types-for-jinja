# Design

Why types-for-jinja is shaped the way it is. Three kinds of thing live here: the decisions that are settled and should not be relitigated, the scope boundary and the reasoning behind each exclusion, and the measurements the design rests on so nobody has to take them again.

Unscheduled work is in [BLUE_SKY.md](./BLUE_SKY.md). Release history is in [docs/CHANGELOG.md](./docs/CHANGELOG.md).

## Origin

Distilled from research into typed templating. Python has no equivalent of Go's templ, Scala's Twirl, or Rust's askama: a template whose context is checked against real host-language types before it runs. Three pieces of prior art shaped the design.

**dbt TypeJinja** (2025) is a static checker over dbt's Jinja IR that found 30 real, previously-unknown type errors. It proves both the demand and the technique. It is also why dbt itself sits outside our scope, since that ecosystem is already served.

**Twirl, templ, and askama** compile a template into a typed host-language function wired into the build, a model all three have shipped for over ten years. We borrow the ergonomics (a typed callable) without becoming a renderer.

**Coffin and Jingo**, both dead Django-Jinja shims, are the anti-pattern. A dual-engine compatibility layer dies once the host framework absorbs the capability, so we do not build a shim.

## Locked decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Execution model | Write a stub, never run a checker | Zero migration. Jinja renders unchanged, and Jinja's own compiler already is the renderer. |
| Type inference | Delegate to whichever checker the project runs | We write no inference engine. Loop-variable narrowing, generics, and attribute checks come free. |
| Language | Python | Native access to Jinja2's parser (`Environment.parse()`) and the user's own types. Trivial pip and pre-commit distribution. |
| Declaration | Comment header, `{#def ... #}` | Self-contained, one line per file, zero coupling, and Jinja parses it as a comment. |
| Stub-to-stub imports | Relative | An absolute dotted name assumes where the checker puts its root, and breaks when the output directory moves. |
| Suppression | Blanket per line, spelled per checker | Rule codes are not portable, and a name a checker does not know is itself an error. |

### Why a stub and not a renderer

**Jinja already ships its own template-to-Python compiler** (`jinja2.compiler.CodeGenerator`). Jinja compiles every template to Python and runs it. That renderer exists and Pallets maintains it. Rebuilding a type-checked copy would mean permanent parity work on filters, escaping, inheritance, and the `foo.bar` then `foo['bar']` fallback. The stub route reports the same errors for a fraction of that code.

The templ/Twirl ergonomic win is a typed function you call instead of a stringly `render('error.html', message=...)`. `types-for-jinja wrapper` captures that with a thin function that **delegates** to Jinja rather than replacing it. The responsibilities split cleanly: the wrapper types the boundary between your Python and the template, the stub types the inside of the template, and Jinja renders unchanged.

### Why we never invoke a checker

An earlier design ran pyright as a subprocess per file and owned its own `TJ###` diagnostic codes. Writing a stub instead is better on five counts, and the whole `check` subcommand was removed once the replacements existed.

The stub is checked under the project's own settings. The subprocess wrote a fresh `pyrightconfig.json`, so the mypy pydantic plugin, custom stub paths, and strictness options never applied to template checks. Now they all do.

There is no pyright-on-PATH requirement and no per-file process. The measured per-file floor was roughly 480 ms for pyright and 49 ms for ty regardless of template size. Over 25 stubs, one batched invocation beat 25 separate ones by 24x (pyright, 12.02 s to 0.498 s) and 33x (ty, 1.22 s to 0.037 s), with identical diagnostics. Writing files gets that batching for free, and the user's checker keeps its incremental cache.

Diagnostics carry the checker's native rule codes, so per-code suppression, baselines, and editor quick-fixes behave exactly as they do for the rest of the codebase. The portability problem that a private code catalog created disappears with the subprocess that made it necessary.

CI, pre-commit, and the editor converge on one mechanism: fresh stubs, checked by whatever already checks the repo.

Three things were lost, and each has a replacement. Template-native paths and columns in CI output come back through `types-for-jinja remap`. `--format json` and SARIF are replaced by the checker's own machine formats, remapped. `TJ###` codes are replaced by native codes, with `{# type: ignore #}` still working through the `suppression` setting.

## Three independent axes

Conflating these made the design look harder than it is.

**Declaration syntax.** Rung 1 is a comment (`{#def user: User #}`), which we control and which Jinja ignores. Rung 2 is an extension tag (`{% types user: User %}`), which we could ship but which couples a project to registering the extension. Rung 3 is first-class Jinja syntax, which belongs to Pallets. The Python parallel is exact: Python shipped `# type:` comments first (PEP 484), and those comments proved the demand that justified native annotation syntax later (PEP 526). We cannot skip to rung 3 because Pallets moves on evidence generated at rungs 1 and 2. Comments are the strategy rather than a phase to get past, and a good editor experience recovers most of what native syntax would add.

**Execution model.** Write a stub (chosen) or replace Jinja with generated code (rejected, see above).

**Delivery.** The CLI serves CI, and the language server plus the editor mirror serve the editor. Delivery does not change either of the other two axes.

## Runtime enforcement is a separate opt-in

One source of truth, the header, drives three levels. This mirrors how Python already works: the annotation is written once, a static checker reads it, and runtime enforcement is a separate opt-in.

Level 0, static only, is the default and the reason people install the tool: zero runtime cost, template-internal errors caught. Level 1 adds the generated wrapper, still static only, moving the render call from stringly to typed. Level 2 decorates that wrapper with a real validator, which catches what static analysis cannot follow: database rows, API JSON, user input, dynamically assembled dicts.

### Types and validators are independent

The header names a type, and that type can be a dataclass, a `TypedDict`, a `Protocol`, a `NamedTuple`, or a Pydantic model. Checkers read Pydantic v2 model fields as ordinary annotated attributes, so attribute access is checked identically to a dataclass with no special-casing.

Which validator enforces Level 2 is a separate choice: none (the default), beartype (checks the value against the annotation and raises, near-zero cost, non-transforming), or a Pydantic `TypeAdapter` (parses and coerces, heavier, best when the context comes from JSON or a database).

The two axes never lock each other, because `pydantic.TypeAdapter` works on any type rather than only `BaseModel`. So `TypeAdapter(SomeDataclass).validate_python(ctx)` validates a dataclass context, and beartype composes even when the context types are Pydantic models.

One honest semantic difference: beartype checks the value and leaves the object alone, while Pydantic parses and can hand the template a new coerced object. So the rendered object is not always the one you passed.

The core stays Pydantic-agnostic and works against plain typing. beartype is the default Level 2 because it is lighter and non-transforming. Pydantic is the boundary-parsing upgrade for FastAPI-style apps.

## Scope boundary

The technique generalizes further than this implementation will. Transpiling a template to a throwaway host-language stub and running the host's type checker over it is engine-agnostic. We are choosing not to chase that, and this section records why so the question stays settled.

**In scope** is Jinja2 together with Jinja supersets and dialects, meaning anything Jinja's own parser reads: plain Jinja2, JinjaX, and the template sets in Flask, Litestar, FastAPI, Copier, and Cookiecutter projects. A superset that adds tags through a Jinja Extension belongs here. A loader that is not backed by files at all (`DictLoader`, a database) still needs the templates on disk to be checked.

**Ansible, Salt, and dbt are out** even though they parse as Jinja. Their contexts are untyped dicts assembled at runtime, so there is no declared type for a checker to check against, and all three lean on large custom filter libraries that collapse to `Any`. dbt already has TypeJinja, which works over dbt's own IR and understands `ref()` and `source()` in a way a generic Jinja checker cannot. Serving these would mean adopting three per-ecosystem filter catalogs plus a context-discovery story per host, none of which carries over to the templates we do serve.

**Engines not hosted in Python are out** for a harder reason. Everything downstream of the AST assumes Python: the stub is Python, a Python checker reads it, and the declared types are Python types. Nunjucks, Twig, Liquid, Handlebars, and Blade would each need their own emitter and their own type checker (`tsc`, PHPStan, Sorbet). That replaces the backend, which makes it a separate product rather than an adapter. templ and askama already solve this natively in Go and Rust.

**Other Python engines are out** for a semantic reason. Django's DTL resolves `{{ a.b }}` as dict key, then attribute, then list index, and calls zero-arg callables implicitly, so most dotted access would widen to `Any` and the checker would stop saying anything useful. Its `{% load %}` tags also carry signatures that live nowhere in the template. Mako embeds real Python already, which makes it an extraction problem of a different shape. Liquid is forgiving by design, where a missing variable rendering empty is correct behaviour, so strict diagnostics read as false positives against the language's own contract.

If this ever reverses, the cost is known. `_emit_node` and `_expr` in `types_for_jinja/transpile.py` pattern-match `jinja2.nodes` directly, and `header.py` builds its patterns from the configured comment delimiters. A second Python-hosted engine would need an engine-neutral IR between the parser and the emitter, covering the dozen node kinds `_emit_node` already switches on. That is a few hundred lines. Do it when a second engine has a user asking for it.

## Backend evidence

Notes from 2026-07-29, revised 2026-08-04. Measured with pyright 1.1.411, ty 0.0.61, and mypy 2.3.0 on macOS. This is the evidence the design rests on, recorded so the measurements never have to be redone.

### All three checkers read the stubs identically

Checked against real generated stubs (dataclass context, bad attribute, undefined name, loop variable, filter call, bad method on `int`): pyright, ty, and mypy each reported the same errors on the same template lines. `tests/test_backends.py` holds that agreement on every run across eight invocations, and CI sets `TYPES_FOR_JINJA_REQUIRE_CHECKERS` so a missing backend fails rather than skips.

Two defects had to be fixed first, and both were invisible under pyright alone. The stub reused one `_` name for every expression check, so mypy took its declared type from the first assignment and reported `Incompatible types in assignment` on every later one. The preamble now declares `_: _TJAny`. The generated filter signatures also had `...` bodies in a real module, which ty reports as `empty-body`, so they raise instead. Those two fixes took ty from 58 diagnostics to the 3 the examples are supposed to have, and mypy from 12 to the same 3.

A third was invisible under any single configuration. The generated stub-to-stub imports used bare module names, which only resolved because ty and mypy infer the output directory as a source root when it has no `__init__.py`. Passing an explicit search path defeats that inference, so `ty check --extra-search-path . .` reported `unresolved-import` on every template using a filter or a cross-file macro. The imports are relative now, over a package marker at the output root, which resolves structurally in every invocation shape measured: from the project root, as a directory argument, as a single file, and with the output directory nested two levels down. The test that should have caught it was running the checkers from inside the stub tree with an explicit `extraPaths`, the one configuration that hid it.

### Line alignment

Measured over 126 templates (11 from `examples/`, 115 real ones from mkdocs-material): 95.2% got an exact line-aligned stub, 2.4% kept `# L` markers, and 2.4% raised `UnsupportedTemplateError`. Both remainders were addressed. A single-line `{% if %}...{% else %}...{% endif %}` collapses to a conditional expression, which narrows the same way the branches did, and `UnsupportedTemplateError` skips one template with a reason rather than ending the run.

Five transformations took alignment from 30% to 95%, each traced to a measured failure:

- hoist `loop` to the preamble so a for-body's first line is free for real statements
- drop the `_render` placeholder `pass`, which carried the header's line number (73 of the original 78 fallbacks)
- route cross-file macro stubs to a sidecar module, since they carry another template's line numbers
- demote `{% if x %}{% endif %}` to `_ = x`, a simple statement that can share a physical line
- relocate `else:`, because Jinja records no line number for `{% else %}`

The preamble collapses onto the header's own line as `;`-joined simple statements, so alignment holds no matter how many imports and globals a project declares. Emitting at module level frees the indent level the template's top level needs, which means every declared name must be bound (`user: User = _tj_any`), not just annotated, or real errors disappear under `"user" is unbound`. Known gap: `loop` is bound at module level, so using `loop` outside a `{% for %}` is not flagged.

The output directory must not start with a dot, because pyright excludes `**/.*` by default and reports a clean run over zero files. Every segment must also be a valid identifier, because the stubs import each other relatively. Stub paths mirror the template tree with only the filename mangled, since a module name cannot carry the template's extension.

### File and line fidelity

Lines are exact: the aligned layout makes generated line N template line N. What remains is the path and the column.

The **path** names the stub. No Python checker honours a `//line`-style directive, so `remap` covers CI and the editor mirror covers editors. The upstream ask is in [BLUE_SKY.md](./BLUE_SKY.md). Do not block on it.

The **column** points into the stub line. Aligned stubs keep template expressions nearly verbatim, so `remap` and the mirror take the identifier the checker pointed at and find it again on the template line, keeping the stub column when the search misses. Measured across all eight backend invocations, the token at the recovered column is always the token the stub column pointed at.

A **sidecar** module holds definitions another template contributed, so no line of it corresponds to a line here. The manifest records it against its template with a fixed line, which is the local `{% extends %}` or `{% include %}` tag, and every position in it reports there.

The rare template with **no aligned form** keeps `# L` markers, which `remap` reads from the stub file.

### What varies between backends

This table is `remap`'s interface spec: everything a per-backend output parser needs.

| | ty | pyright | mypy |
| --- | --- | --- | --- |
| import path | `--extra-search-path DIR` | `extraPaths` in `pyrightconfig.json` | `MYPYPATH` env |
| machine output | `--output-format gitlab\|github\|junit` or `concise` | `--outputjson` | `--output json` |
| line base | 1 | 0 in JSON, 1 in text | 1 |
| column base | 1 | 0 in JSON, 1 in text | 0 in JSON, 1 in text |
| undefined name | `unresolved-reference` | `reportUndefinedVariable` | `name-defined` |
| bad attribute | `unresolved-attribute` | `reportAttributeAccessIssue` | `attr-defined` |
| bad index | `invalid-argument-type` | `reportArgumentType` / `reportCallIssue` | `index` / `call-overload` |
| member detail | in `detail` | only on `completionItem/resolve`, in `documentation` | n/a |

The member-detail row is why the language server declares `resolveSupport` and reads either field: without it, pyright's completion popup lists member names with no types beside them.

### Suppression

Rule codes are not portable across backends (the same error files under a different name per checker, and the mapping is one-to-many), which is why suppression drops codes rather than translating them. Measured behaviour of a bare ignore comment:

| | pyright | ty | mypy |
| --- | --- | --- | --- |
| `# type: ignore` | suppresses | suppresses | suppresses |
| `# ty: ignore` | no | suppresses | no |
| `# pyright: ignore` | suppresses | no | no |
| `# type: ignore[<code>]` | suppresses | no | suppresses |

So `{# type: ignore #}` (with or without a bracketed code) emits one blanket ignore on the aligned line, spelled per `[tool.types_for_jinja] suppression`: `portable` (the default, `# type: ignore`), or `mypy`, `pyright`, `ty`. An unknown value is rejected at config load, because a silent fallback would emit comments the project's checker does not honour. Stacking (`# type: ignore  # ty: ignore`) was ruled out because ty reports `unused-ignore-comment` on the second directive. On an unaligned fallback line the ignore goes in front of the `# L<n>` marker, since a checker only honours the directive when it opens the comment.

### Member resolution

`ty server` answers member completions today. Measured against the fixture project it returns the same members as pyright with the same types, in 1-3 ms warm against pyright's 7-16 ms (cold start 32 ms against 525 ms). Both are reused across queries, so only the warm figure matters in an editor.

## Validation targets

1. Standalone examples in `examples/`: `templates`, `crossfile`, `realworld`, and `runtime`.
1. The yak-shears project, the real migration test. Its templates carry `{#def #}` headers.
1. A demo Flask app as a later, optional showcase. Django only qualifies when it renders Jinja through `django-jinja`, because DTL is out of scope.

### What the yak-shears spike found

Run against real templates using `{% extends %}`/`{% block %}` inheritance (26 blocks, 7 extends), `{% if %}`/`{% for %}`/`{% set %}`, and filters (`length`, `tojson`, `title`, `sort`, `min`, `max`, `join`, `format`, `default`).

What worked: on `error.html.jinja` (extends `base.html.jinja`, fills `{% block content %}` with `{{ message }}`), the transpiler extracted and checked the expressions inside the block. A correct header passes clean, and a `mesage` typo is caught at the right line.

Two gaps it surfaced, both since closed. **Jinja Environment globals** (`static_url()`, `url_for()`, `get_flashed_messages()`) are injected into `Environment.globals` rather than passed per render, so a template calling one was flagged as an undefined variable. Globals are now declared once in `[tool.types_for_jinja]`. The second was **inheritance context flow**, because a child template's effective context spans the child and its base. Whole `{% extends %}` chains and `{% include %}` bodies now check against the including template's context.
