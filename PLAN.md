# types-for-jinja — implementation plan

A static type checker for Jinja2 templates, and for Jinja supersets and dialects. It validates the variables, attribute access, and control flow inside a template against a typed context you declare, with no new template language and no runtime cost by default. See "Scope boundary" for what that phrase does and does not include.

## Origin

Distilled from research (see the "Python templating libraries with type support" chat). Python has no equivalent of Go's templ, Scala's Twirl, or Rust's askama: a template whose context is checked against real host-language types before it runs. Prior art that shaped the design:

- **dbt TypeJinja** (2025), a static checker over dbt's Jinja IR that found 30 real, previously-unknown type errors. It proves the demand and the technique. It is also why dbt itself sits outside our scope, since that ecosystem is already served.
- **Twirl / templ / askama**, which compile a template into a typed host-language function wired into the build. Durable for 10+ years. We borrow the ergonomics of this model (a typed callable) without becoming a renderer. See "Architecture".
- **Coffin / Jingo** (dead Django-Jinja shims), the anti-pattern. A dual-engine compatibility layer dies once the host framework absorbs the capability. We do not build a shim.

## Scope boundary

The technique generalizes further than this implementation will. Transpiling a template to a throwaway host-language stub and running the host's type checker over it is engine-agnostic. We are choosing not to chase that, and this section records why so the question stays settled.

In scope is Jinja2 together with Jinja supersets and dialects, meaning anything Jinja's own parser reads: plain Jinja2, JinjaX, and the template sets in Flask, Litestar, FastAPI, Copier, and Cookiecutter projects. A superset that adds tags through a Jinja Extension belongs here. Delimiters are declared once under `[tool.types_for_jinja.syntax]` using `jinja2.Environment`'s own keyword names, and `template_dirs` accepts a `package:subdirectory` entry for templates shipped inside an installed package, which is what `PackageLoader` reads. A loader that is not backed by files at all (`DictLoader`, a database) still needs the templates on disk to be checked.

Ansible, Salt, and dbt are out even though they parse as Jinja. Their contexts are untyped dicts assembled at runtime, so there is no declared type for a checker to check against, and all three lean on large custom filter libraries that `_filtered` collapses to `Any`. dbt already has TypeJinja, which works over dbt's own IR and understands `ref()` and `source()` in a way a generic Jinja checker cannot. Serving these would mean adopting three per-ecosystem filter catalogs plus a context-discovery story per host, and none of that work carries over to the templates we do serve.

Engines not hosted in Python are out for a harder reason. Everything downstream of the AST assumes Python: the stub is Python, pyright checks it, and the declared types are Python types. Nunjucks, Twig, Liquid, Handlebars, and Blade would each need their own emitter and their own type checker (`tsc`, PHPStan, Sorbet). That replaces the backend, which makes it a separate product rather than an adapter. templ and askama already solve this natively in Go and Rust.

Other Python engines are out for a semantic reason. Django's DTL resolves `{{ a.b }}` as dict key, then attribute, then list index, and calls zero-arg callables implicitly, so most dotted access would widen to `Any` and the checker would stop saying anything useful. Its `{% load %}` tags carry signatures that live nowhere in the template. Mako embeds real Python already, which makes it an extraction problem of a different shape. Liquid is forgiving by design, where a missing variable rendering empty is correct behavior, so strict diagnostics read as false positives against the language's own contract.

If this ever reverses, the cost is known. `_emit_node` and `_expr` in `types_for_jinja/transpile.py` pattern-match `jinja2.nodes` directly, and `header.py` hardcodes the `{# #}` comment form. A second Python-hosted engine would need an engine-neutral IR between the parser and the emitter, covering the dozen node kinds `_emit_node` already switches on. That is a few hundred lines. Do it when a second engine has a user asking for it.

## Design axes

Three decisions are independent. Earlier discussion conflated them, which made the roadmap look harder than it is. Separating them is what keeps each rung cheap.

### Axis 1: declaration syntax (how you write the contract)

| Rung               | Form                     | Who grants it                        | Coupling                                                  |
| ------------------ | ------------------------ | ------------------------------------ | --------------------------------------------------------- |
| 1. Comment         | `{#def user: User #}`    | us, today                            | none, because Jinja parses it as a comment and ignores it |
| 2. Extension tag   | `{% types user: User %}` | us, via a registered Jinja Extension | must register the extension on the `Environment`          |
| 3. Upstream native | first-class Jinja syntax | Pallets, after we prove demand       | none, because it is just Jinja                            |

We control rungs 1 and 2. Rung 3 belongs to Pallets.

The Python parallel is exact. Python shipped `# type:` comments first (PEP 484). Those comments were the on-ramp that proved demand and justified native annotation syntax later (PEP 526). We cannot skip to rung 3 because it needs Pallets, and Pallets moves on evidence we generate at rungs 1 and 2. Comments are the strategy, not a phase to rush past. dbt TypeJinja is our proof-of-demand analog, and a good LSP (Axis 3) closes most of the ergonomic gap that native syntax would otherwise close.

### Axis 2: execution model (what the tool does)

- **Checker (our choice).** Transpile the template to a discarded Python stub, let pyright check it, and let Jinja render at runtime unchanged. Zero migration, because the only edit to a template is one comment line.
- **Renderer (rejected).** Replace Jinja with generated code. This forces full parity with Jinja's runtime (all filters, escaping, inheritance, the `foo.bar` then `foo['bar']` fallback) and a permanent maintenance treadmill. See "Architecture" for why this buys nothing the checker cannot get more cheaply.

### Axis 3: delivery (how diagnostics reach the developer)

The LSP is a separate layer that surfaces the checker's diagnostics, completions, and hovers in the editor. It is what makes comment-declared types feel first-class without needing rung 3. CLI and pre-commit deliver the same diagnostics to CI. Delivery does not change either of the other two axes.

## Architecture

We stay a checker (Axis 2), and we do not build a renderer, for one concrete reason: **Jinja already ships its own template-to-Python compiler** (`jinja2.compiler.CodeGenerator`). Jinja compiles every template to Python and runs it. That renderer exists and Pallets maintains it. Rebuilding a type-checked copy would sign us up for the parity treadmill and buy nothing the checker route cannot get more cheaply.

The templ/Twirl ergonomic win is a typed function you call instead of a stringly `render('error.html', message=...)`. We capture that with a thin wrapper that **delegates** to Jinja rather than replacing it:

```python
# generated, opt-in, one per template
def render_error(*, message: str) -> Markup:
    return _env.get_template('error.html.jinja').render(message=message)
```

The responsibilities split cleanly:

- the **wrapper** types the boundary between your Python and the template (calling `render_error(mesage=...)` or `render_error(message=123)` is a pyright error)
- the **checker** types the inside of the template (a `{{ mesage }}` typo in the body)
- **Jinja** renders, unchanged

This is the sharpened "phase 2 codegen": a delegating wrapper, not a reimplemented renderer. It is cheap because we already parse the header the wrapper needs.

### Locked decisions

| Decision        | Choice                                      | Why                                                                                                                                                 |
| --------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Execution model | **Checker** (transpile to a discarded stub) | Zero migration. Jinja renders unchanged. Its own compiler already is the renderer.                                                                  |
| Type inference  | **Delegate to pyright**                     | We write no inference engine. Loop-variable narrowing, generics, and attribute checks come free.                                                    |
| Language        | **Python**                                  | Native access to Jinja2's parser (`Environment.parse()`) and the user's own types (`typing.get_type_hints`). Trivial pip / pre-commit distribution. |
| Declaration     | **Comment header** (`{#def ... #}`), rung 1 | Self-contained, one line per file, zero coupling. Rung 2 is a later opt-in.                                                                         |
| v1 checks       | Undefined variables + attribute/key access  | Undefined vars fall out of pyright's `reportUndefinedVariable`, bad attributes from `reportAttributeAccessIssue`.                                   |

Two rows moved in the 2026-08 pivot below: the stub is written rather than discarded, and inference delegates to whichever checker the project already runs rather than to pyright specifically. The rest hold.

## Direction (2026-08): generate-only on a jinja2-only core

Decided after the backend evidence (below) proved pyright, ty, and mypy read the aligned stubs identically. `types-for-jinja generate` becomes the product and `check` is removed. The runtime dependency list shrinks to `jinja2` alone (corallium moves to the dev group; only tests use it). types-for-jinja never invokes a type checker: it writes Python, and the project's own checker reports template errors, under the project's own configuration, in the run it already does. The pitch changes from "a checker for templates" to "your checker now covers templates".

### What this buys

- The stub is checked under the project's own checker settings. `check` wrote a fresh `pyrightconfig.json`, so the mypy pydantic plugin, custom stub paths, and strictness options never applied to template checks. With generate they all do, which closes the last item in "Open questions".
- No pyright-on-PATH requirement, no per-file subprocess, no `PyrightNotFoundError` path. The user's checker pays one startup and keeps its incremental cache. The measured per-file floor is roughly 480ms for pyright and 49ms for ty; generate writes files and gets batching for free.
- Diagnostics carry the checker's native rule codes, so per-code suppression, baselines, and editor quick-fixes behave exactly as they do for the rest of the codebase. The TJ catalog and its cross-backend portability problem disappear with the subprocess that made them necessary.
- CI, pre-commit, and the editor converge on one mechanism: fresh stubs, checked by whatever already checks the repo.

### What it costs, and the replacement for each

| Lost with `check`                              | Replacement                                                                                                      |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Template-native paths and columns in CI output | `types-for-jinja remap`, a stdout filter over the checker's output (below)                                       |
| `--format json` / SARIF                        | the checker's own machine formats (`pyright --outputjson`, `mypy --output json`, `ty --output-format`), remapped |
| `TJ###` codes                                  | native checker codes; `{# type: ignore #}` still works through the `suppression` setting                         |
| Diagnostics with zero project setup            | one `generate` call plus the checker the project already runs                                                    |

### Pathway

Ordered so each step lands independently. `check` is deleted last, after its replacements exist.

1. **Docs.** README rewritten and BACKENDS.md merged into "Backend evidence" below (both done pre-emptively), CHANGELOG entry, and docs/BLUE_SKY.md holding the unscheduled items.

### File and line fidelity

Lines are exact: the aligned layout makes generated line N template line N, and the two residual causes measured in "Backend evidence" were fixed. What remains:

- The **path** names the stub. No Python checker honors a `//line`-style directive, so `remap` covers CI and mirroring covers editors. The upstream ask (a `# file:` pragma, ty first) lives in docs/BLUE_SKY.md; do not block on it.
- The **column** points into the stub line. Aligned stubs keep template expressions nearly verbatim, so `remap` and the mirror search for the expression text on the template line and keep the stub column when the search misses.
- The rare template with no aligned form keeps `# L` markers, which `remap` reads from the stub file.

### JinjaX and jinja-adjacent coverage

JinjaX is where the `{#def #}` header comes from, so its templates should check without translation. Gaps, in priority order:

1. **Header defaults and the one-line form.** JinjaX writes `{#def action, method: str = "post" #}`: comma-separated, defaults allowed, untyped names allowed. `header.py` is line-based and reports `str = "post"` as a malformed annotation. Parse defaults (the wrapper signature carries them), accept the comma-separated form beside the line-per-entry form, and type a bare name as `Any`.
1. **Component tags.** `<Card title={{ x }} />` is JinjaX preprocessor syntax. Jinja's parser reads it as literal text plus output nodes, so the embedded `{{ x }}` is checked today and the component boundary is not. The aligned-stub answer: scan text nodes for PascalCase tags, resolve `Card` to its component template, and emit the use as a call against a signature generated from that component's own `{#def #}`. The user's checker then validates attribute names, types, and required-versus-defaulted, with no dependency on jinjax itself.
1. **`{#css#}` and `{#js#}` blocks** parse as comments and are ignored, which is correct.

Beyond JinjaX:

- **Extension tags.** `{% trans %}`, `{% do %}`, and `{% break %}` fail `Environment.parse` when the extension is not loaded, so those templates are skipped today. Add `[tool.types_for_jinja] extensions = [...]`, loaded into the parsing Environment. The stock extensions ship inside jinja2, so the dependency list is unchanged; enabling i18n also injects `_`, `gettext`, and `ngettext` as known globals.
- **`namespace()`.** `{% set ns.count = 1 %}` currently skips the whole template. Model `namespace` as a known global whose result accepts any attribute, so the rest of the template still checks.
- **Discovery.** `_iter_templates` globs only `*.html` and `*.jinja`. Add `*.j2`, a `template_globs` setting, and a fallback to `template_dirs` when no paths are given.
- **Copier and Cookiecutter** need only what exists: configured delimiters, `template_dirs`, and declared globals.

Still ruled out, per "Scope boundary": Ansible, Salt, dbt, engines not hosted in Python, and DTL, Mako, and Chameleon.

## Backend evidence

Merged from the standalone BACKENDS.md (notes from 2026-07-29, revised 2026-08-04). Measured with pyright 1.1.411, ty 0.0.61, and mypy 2.3.0 on macOS. This is the evidence the Direction above rests on, condensed so the measurements never have to be redone; what described the retired `check` subprocess is dropped.

### All three checkers read the stubs identically

Checked against real generated stubs (dataclass context, bad attribute, undefined name, loop variable, filter call, bad method on `int`): pyright, ty, and mypy each reported the same errors on the same template lines. `tests/test_backends.py` holds that agreement on every run, and CI sets `TYPES_FOR_JINJA_REQUIRE_CHECKERS` so a missing backend fails rather than skips.

Two defects had to be fixed first, and both were invisible under pyright alone:

- the stub reused one `_` name for every expression check, so mypy took its declared type from the first assignment and reported `Incompatible types in assignment` on every later one. The preamble declares `_: _TJAny`
- the generated filter signatures had `...` bodies in a real module, which ty reports as `empty-body`. They raise instead

Those two fixes took ty from 58 diagnostics to the 3 the examples are supposed to have, and mypy from 12 to the same 3.

### Line alignment

Measured over 126 templates (11 from `examples/`, 115 real ones from mkdocs-material): 95.2% got an exact line-aligned stub, 2.4% kept `# L` markers, and 2.4% raised `UnsupportedTemplateError`. Both remainders were addressed: single-line `{% if %}...{% else %}...{% endif %}` collapses to a conditional expression (which narrows the same way the branches did), and `UnsupportedTemplateError` skips one template with a reason rather than ending the run (`{% set ns.count = 1 %}` is the common trigger; see "namespace()" above).

Five transformations got alignment from 30% to 95%, each traced to a measured failure:

- hoist `loop` to the preamble so a for-body's first line is free for real statements
- drop the `_render` placeholder `pass`, which carried the header's line number (73 of the original 78 fallbacks)
- route cross-file macro stubs to a sidecar module, since they carry another template's line numbers
- demote `{% if x %}{% endif %}` to `_ = x`, a simple statement that can share a physical line
- relocate `else:`, because Jinja records no line number for `{% else %}`

The preamble collapses onto the header's own line as `;`-joined simple statements, so alignment holds no matter how many imports and globals a project declares. Emitting at module level frees the indent level the template's top level needs, which means every declared name must be bound (`user: User = _tj_any`), not just annotated, or real errors disappear under `"user" is unbound`. Known gap: `loop` is bound at module level, so using `loop` outside a `{% for %}` is not flagged.

The output directory must not start with a dot: pyright excludes `**/.*` by default and reports a clean run over zero files, which is why the default is `_jinja_stubs`. Stub paths mirror the template tree with only the filename mangled, because a module name cannot carry the template's extension.

### What varies between backends

This table is `remap`'s interface spec: everything a per-backend output parser needs.

|                | ty                                                   | pyright                                  | mypy                      |
| -------------- | ---------------------------------------------------- | ---------------------------------------- | ------------------------- |
| import path    | `--extra-search-path DIR`                            | `extraPaths` in `pyrightconfig.json`     | `MYPYPATH` env            |
| machine output | `--output-format gitlab` (JSON) or `concise` (regex) | `--outputjson`                           | `--output json`           |
| line base      | 1                                                    | 0                                        | 1                         |
| column base    | 1                                                    | 0                                        | 0                         |
| undefined name | `unresolved-reference`                               | `reportUndefinedVariable`                | `name-defined`            |
| bad attribute  | `unresolved-attribute`                               | `reportAttributeAccessIssue`             | `attr-defined`            |
| bad index      | `invalid-argument-type`                              | `reportArgumentType` / `reportCallIssue` | `index` / `call-overload` |

### Suppression

Rule codes are not portable across backends (the same error files under a different name per checker, and the mapping is one-to-many), which is why suppression drops codes rather than translating them. Measured behaviour of a bare ignore comment:

|                          | pyright    | ty         | mypy       |
| ------------------------ | ---------- | ---------- | ---------- |
| `# type: ignore`         | suppresses | suppresses | suppresses |
| `# ty: ignore`           | no         | suppresses | no         |
| `# pyright: ignore`      | suppresses | no         | no         |
| `# type: ignore[<code>]` | suppresses | no         | suppresses |

So `{# type: ignore #}` (with or without a bracketed code) emits one blanket ignore on the aligned line, spelled per `[tool.types_for_jinja] suppression`: `portable` (the default, `# type: ignore`), or `mypy`, `pyright`, `ty`. An unknown value is rejected at config load, because a silent fallback would emit comments the project's checker does not honour. Stacking (`# type: ignore  # ty: ignore`) was ruled out because ty reports `unused-ignore-comment` on the second directive. On an unaligned fallback line the ignore goes in front of the `# L<n>` marker, since a checker only honours the directive when it opens the comment.

### Performance

Startup dominates per-file checking: the floor is roughly 480ms per pyright invocation and 49ms per ty invocation, regardless of template size. Over 25 stubs, one batched invocation beat 25 separate ones 24x (pyright, 12.02s to 0.498s) and 33x (ty, 1.22s to 0.037s), with identical diagnostics. `generate` collects the whole win by construction: the user's checker pays one startup over the stub tree and keeps its own incremental cache. Neither checker benefits from added process-level parallelism; both already run above 100% CPU batched. To reproduce: 25 stubs shaped like transpiler output, each with one deliberate bad attribute, shell loop versus single directory invocation, confirming equal diagnostic counts before trusting timings.

## How it works

```
template.html ──parse header──► param signature
      │
      └──env.parse()──► Jinja AST ──transpile──► generated Python stub
                                                        │
                                          pyright --outputjson
                                                        │
                                   map generated-line errors ──► template:line diagnostics
```

The transpiler walks the Jinja AST and emits, for every expression the template uses, a Python statement that exercises it (`_ = user.name`), preserving nesting so pyright's scope and narrowing mirror Jinja's. `{% for i in items %}` becomes `for i in items:`, so pyright infers `i: Item` and checks `{{ i.title }}` for free. Each generated line carries a `# L<n>` marker back to its template line, and pyright errors are remapped through those markers. Both undefined variables and bad attributes come from pyright at zero inference cost, which is the whole point of the checker route.

## Runtime model

One source of truth, the header, drives three opt-in levels. This mirrors how the project already treats Python: the annotation is written once, a static checker reads it, and runtime enforcement is a separate opt-in.

- **Level 0, static only (default).** pyright over the stub. Zero runtime cost. Catches template-internal errors. This is the whole v1 pitch, and it is the reason people install the tool.
- **Level 1, typed call site (opt-in codegen).** The delegating wrapper from "Architecture". Still static only, still zero runtime cost. It moves the render call from stringly to typed so the boundary is checked by pyright.
- **Level 2, runtime enforcement (opt-in).** The generated wrapper carries real annotations, so a runtime validator can check the context at render time. This catches what static analysis cannot follow (database rows, API JSON, user input, dynamically assembled dicts). Which validator runs is a separate choice (none, beartype, or Pydantic), covered in "Types and validators". The tradeoff matches beartype: run it in dev and test, or leave it on at boundaries in production because it is cheap.

Two delivery options for Level 2, ship (a) first:

- **(a) Decorate the generated wrappers.** Reuse beartype or Pydantic as-is. No new runtime engine to build. Built as a working proof in `examples/runtime`: `types_for_jinja.wrapper.generate_wrapper(header, name, validator=...)` emits the typed function, and `validator='beartype'` decorates it while `validator='pydantic'` validates each parameter through a `TypeAdapter` before rendering. Tests confirm beartype raises on a wrong type and Pydantic coerces a dict then rejects a bad one.
- **(b) A `TypedEnvironment(jinja2.Environment)`** whose `.render()` reads the header, resolves the declared types by evaluating the annotation strings in the header's import namespace (the way `get_type_hints` does), validates the context, then delegates to normal Jinja rendering.

The framing to hold onto: the header is the annotation, pyright is mypy, and the runtime validator is the opt-in enforcement of that same annotation. Default off, because the zero-cost static checker is why people install it.

## Types and validators: two axes

Pydantic is optional on two independent axes, and it is never a hard dependency. The core works against plain typing with no Pydantic in the required path.

### Axis 1: what the context types are

The header imports and names a type. That type can be a dataclass, a `TypedDict`, a `Protocol`, a `NamedTuple`, or a Pydantic model. The checker and the wrapper are agnostic to which. pyright reads Pydantic v2 model fields as ordinary annotated attributes, so attribute access is checked identically to a dataclass with zero special-casing. Choosing a Pydantic model buys computed fields, validated invariants, and `.model_dump()` feeding the `tojson` filter.

### Axis 2: which runtime validator enforces Level 2

- **none**: static only, the default.
- **beartype**: checks the value against the annotation and raises. Near-zero cost. Non-transforming, so the object the template receives is the object you passed.
- **Pydantic `TypeAdapter`**: parses and coerces the context into a validated object. Heavier. Best when the context comes from JSON, a database, or form input.

Axis 2 is independent of Axis 1.

### The compatibility fact

`pydantic.TypeAdapter` works on any type, not only `BaseModel`. So `TypeAdapter(SomeDataclass).validate_python(ctx)` validates a dataclass context. Pydantic-as-validator composes even when the context types are plain dataclasses, and beartype composes even when the context types are Pydantic models. The axes never lock each other.

Level 2 wrapper with the Pydantic validator:

```python
from pydantic import TypeAdapter

_ctx = TypeAdapter(User)


def render_profile(*, user: User) -> Markup:
    user = _ctx.validate_python(user)
    return _env.get_template('profile.html.jinja').render(user=user)
```

One honest semantic difference to label in the docs: beartype checks the value and leaves the object alone, while Pydantic parses and can hand the template a new coerced object. Parse-mode should be opt-in and labeled "validate and transform" so nobody is surprised that the rendered object differs from the one they passed.

### Recommendation

The core stays Pydantic-agnostic and works against plain typing. Pydantic is optional on both axes. beartype is the default Level 2 because it is lighter and non-transforming. Pydantic is the boundary-parsing upgrade for FastAPI-style apps. Positioning line: bring your own types (dataclass or Pydantic), bring your own runtime enforcement (none, beartype, or Pydantic).

## Roadmap and tablestakes staging

| Capability                        | Stage            | Why                                                                                                                             |
| --------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| CLI + non-zero exit               | v1               | cheap, already built                                                                                                            |
| JSON / SARIF output               | v1               | the AI-ready and CI story. SARIF plugs into GitHub code scanning and agents. A `--format` flag over data we already have        |
| Environment globals declaration   | v1               | without it `static_url()` is a false positive. A tool that cries wolf gets uninstalled. Enjoyability blocker                    |
| Stable rule codes and catalog     | v1.1             | agents and humans reference and suppress specific checks                                                                        |
| LSP (diagnostics in the template) | v1.1 fast-follow | the ergonomic multiplier. A real build (map template-to-stub positions, proxy pyright). CI value lands first via CLI/pre-commit |
| Typed wrapper codegen             | v1.1             | the native-callable win, opt-in per file                                                                                        |
| Extension-tag syntax (rung 2)     | v1.2+            | only after demand is proven                                                                                                     |

v1 is a checker that is quiet (globals), scriptable (JSON/SARIF), and drops into CI (CLI/pre-commit).

### Status (current build)

- Shipped (v1): the checker (undefined variables plus attribute and item access), the CLI with `--format text|json|sarif`, the Environment globals declaration, a pre-commit hook, and hardening (template-syntax and missing-pyright handling, broader Jinja coverage).
- Shipped (v1.1): the LSP with Neovim integration, live unsaved-buffer checking (debounced so pyright does not queue behind keystrokes), and completion and hover for the typed context's own names, scoped per line and tolerant of the half-typed buffer that completion runs against; macro bodies, with a macro's own `{#def #}` block typing its parameters for its body and its callers across files; cross-file `{% extends %}` base-context and `{% import %}`/`{% from import %}` macro resolution; stable rule codes (`TJ###`) with inline `{# type: ignore #}` suppression.
- Shipped (v1.1): `types-for-jinja wrapper`, which writes one typed render function per template with `--check` for CI, reads `[tool.types_for_jinja.wrapper]`, and takes a `--return-type` so a framework response class replaces `Markup`. Level-2 enforcement (`--validator beartype|pydantic`) rides on the same command; `examples/runtime` remains the runnable proof of both validators.
- Shipped (v1.1): `{% include %}` context flow (the include is checked against the including template's context) and multi-level `{% extends %}` chains, both cycle-safe, with cross-file errors reported at the `{% include %}` or `{% extends %}` line of the file being checked rather than at a line number from another file.
- Shipped (v1.1): attribute completion after a `.`, delegated to `pyright-langserver` over a probe module that is the transpiled stub truncated at the cursor, so a loop variable offers its element's members. Consistent with the locked decision to write no inference engine.
- Shipped (v1.1): LSP completions that follow the cursor, offering built-in filters after `|` (with their return type), built-in tests after `is`, and Jinja tags after `{%`, with hover for all three.
- Shipped (v1.1): configurable delimiters (`[tool.types_for_jinja.syntax]`) and `package:subdirectory` template directories, so a Jinja superset and a `PackageLoader` layout both check.
- Shipped (v1.1): return types for Jinja's built-in filters and tests, emitted as an importable signature module beside the generated code, so a filtered expression keeps a real type instead of collapsing to `Any`. Argument types stay `Any` on purpose; an unknown filter still falls back to `Any`.

## Scope

**v1:**

- `{#def ... #}` header parsing (imports + `name: Type` params)
- Transpile: output `{{ }}`, `{% for %}`, `{% if %}/{% elif %}/{% else %}`, `{% set %}`, attribute/item access, comparisons, boolean/binary ops, filters (operand checked; built-in filters carry their return type since v1.1)
- pyright invocation + line remapping
- Environment globals declaration (kills the `static_url()` false positive)
- JSON / SARIF output
- CLI `types-for-jinja check <paths>` with non-zero exit on errors

**Landed in v1.1 (see Status above):** the LSP with live-buffer checking plus context, member, filter, test, and tag completion; typed macro parameters; cross-file `{% extends %}` chains, `{% include %}`, and `{% import %}` context; built-in filter return types; configurable delimiters and package template directories; `types-for-jinja wrapper`; and rule codes with inline suppression.

**Still deferred:**

- Attribute completion through a parenthesised or filtered base (`(items | first).`), which needs the fragment transpiled to Python before the language server sees it
- Custom (project-defined) extensions beyond the stock jinja2 ones the `extensions` setting covers

Everything unscheduled with no committed pathway (upstream asks, framework adapters, sidecar binding, third-party filter catalogs, `DictLoader`, rung 2, a second engine) lives in docs/BLUE_SKY.md.

Ruled out entirely, per "Scope boundary": Ansible, Salt, and dbt; engines not hosted in Python; and Python engines with different lookup semantics (DTL, Mako, Chameleon).

## Validation targets

1. A tiny standalone example in `examples/` (done: `examples/templates`, `examples/crossfile`, `examples/realworld`, `examples/runtime`).
1. The user's **yak-shears** project, the real migration test (done: its templates carry `{#def #}` headers, and it consumes the package pending the PyPI publish).
1. A demo Flask app as a later, optional showcase. Django only qualifies when it renders Jinja through `django-jinja`, because DTL is out of scope.

## Validation findings (spike, run against yak-shears)

Ran the spike against real templates in `~/Developer/kyleking/yak-shears/yak_shears/_templates`. Those templates use `{% extends %}`/`{% block %}` inheritance (26 blocks, 7 extends), `{% if %}`/`{% for %}`/`{% set %}`, and filters (`length`, `tojson`, `title`, `sort`, `min`, `max`, `join`, `format`, `default`).

What worked: on `error.html.jinja` (extends `base.html.jinja`, fills `{% block content %}` with `{{ message }}`), the transpiler skips the inheritance nodes it does not model yet but still extracts and checks the expressions inside the block. A correct header (`message: str`) passes clean, and a `mesage` typo is caught at the right line.

Two concrete gaps this surfaced, now pulled into the v1 scope above:

1. **Jinja Environment globals** (`static_url()`, `url_for()`, `get_flashed_messages()`). These are injected into `Environment.globals`, not passed per render, so a template that calls one gets flagged as an undefined variable (false positive). v1 needs a project-level declaration of global names/signatures (a config file or a `{#globals#}` header) so the checker treats them as defined. Highest-value fix for Flask and any real app.
1. **Inheritance context flow.** A child template's effective context spans the child and its base (and any `{% include %}`). v1 checked one file at a time, so variables a base template needed were not cross-checked against the child's header. Shipped in v1.1: whole `{% extends %}` chains and `{% include %}` bodies check against the including template's context.

## Open questions

None open. The last one (the stub being checked under a fresh `pyrightconfig.json` rather than the project's own settings) is closed by the Direction above: `generate` inherits the project's checker configuration because the project's checker is the only one that runs.

Resolved, recorded so they stay settled: the wrapper's return type is configurable (`--return-type` / `return_type`), so an app returning `HTMLResponse` generates the whole function rather than only an inner render; a helper that also sets a status code or does work before rendering stays hand-written and calls the generated function. The `{#def ... #}` header survived the yak-shears migration, so no sidecar for now (sidecar binding is in docs/BLUE_SKY.md). Globals are declared once in `[tool.types_for_jinja]` in pyproject.toml, not per template. `types-for-jinja generate` is the product and is verified against pyright, ty, and mypy on every CI run; `check` and its `TJ###` codes are retired per the Direction (measurements and the suppression table are in "Backend evidence"). A template ignore becomes one blanket ignore comment on the generated line, spelled per `[tool.types_for_jinja] suppression`, because per-code names differ between checkers and a wrong one fails to suppress. What no generated stub can carry is the template's own path and column: your checker names the stub, and Python has no equivalent of Go's `//line` directive for type checkers, which is why templ can do this and we cannot (the upstream ask is in docs/BLUE_SKY.md). The editor path has template positions through the mirror; CI output recovers them through `types-for-jinja remap`. `{% import %}` macros, `{% include %}` bodies, and whole `{% extends %}` chains all resolve cross-file since v1.1.
