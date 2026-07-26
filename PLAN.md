# typed-jinja — implementation plan

A static type checker for Jinja2 templates. It validates the variables, attribute
access, and control flow inside a template against a typed context you declare, with
no new template language and no runtime cost by default.

## Origin

Distilled from research (see the "Python templating libraries with type support"
chat). Python has no equivalent of Go's templ, Scala's Twirl, or Rust's askama:
a template whose context is checked against real host-language types before it runs.
Prior art that shaped the design:

- **dbt TypeJinja** (2025), a static checker over dbt's Jinja IR that found 30 real,
  previously-unknown type errors. It proves the demand and the technique.
- **Twirl / templ / askama**, which compile a template into a typed host-language
  function wired into the build. Durable for 10+ years. We borrow the ergonomics of
  this model (a typed callable) without becoming a renderer. See "Architecture".
- **Coffin / Jingo** (dead Django-Jinja shims), the anti-pattern. A dual-engine
  compatibility layer dies once the host framework absorbs the capability. We do not
  build a shim.

## Design axes

Three decisions are independent. Earlier discussion conflated them, which made the
roadmap look harder than it is. Separating them is what keeps each rung cheap.

### Axis 1: declaration syntax (how you write the contract)

| Rung | Form | Who grants it | Coupling |
| --- | --- | --- | --- |
| 1. Comment | `{#def user: User #}` | us, today | none, because Jinja parses it as a comment and ignores it |
| 2. Extension tag | `{% types user: User %}` | us, via a registered Jinja Extension | must register the extension on the `Environment` |
| 3. Upstream native | first-class Jinja syntax | Pallets, after we prove demand | none, because it is just Jinja |

We control rungs 1 and 2. Rung 3 belongs to Pallets.

The Python parallel is exact. Python shipped `# type:` comments first (PEP 484). Those
comments were the on-ramp that proved demand and justified native annotation syntax
later (PEP 526). We cannot skip to rung 3 because it needs Pallets, and Pallets moves
on evidence we generate at rungs 1 and 2. Comments are the strategy, not a phase to
rush past. dbt TypeJinja is our proof-of-demand analog, and a good LSP (Axis 3) closes
most of the ergonomic gap that native syntax would otherwise close.

### Axis 2: execution model (what the tool does)

- **Checker (our choice).** Transpile the template to a discarded Python stub, let
  pyright check it, and let Jinja render at runtime unchanged. Zero migration, because
  the only edit to a template is one comment line.
- **Renderer (rejected).** Replace Jinja with generated code. This forces full parity
  with Jinja's runtime (all filters, escaping, inheritance, the `foo.bar` then
  `foo['bar']` fallback) and a permanent maintenance treadmill. See "Architecture" for
  why this buys nothing the checker cannot get more cheaply.

### Axis 3: delivery (how diagnostics reach the developer)

The LSP is a separate layer that surfaces the checker's diagnostics, completions, and
hovers in the editor. It is what makes comment-declared types feel first-class without
needing rung 3. CLI and pre-commit deliver the same diagnostics to CI. Delivery does
not change either of the other two axes.

## Architecture

We stay a checker (Axis 2), and we do not build a renderer, for one concrete reason:
**Jinja already ships its own template-to-Python compiler** (`jinja2.compiler.CodeGenerator`).
Jinja compiles every template to Python and runs it. That renderer exists and Pallets
maintains it. Rebuilding a type-checked copy would sign us up for the parity treadmill
and buy nothing the checker route cannot get more cheaply.

The templ/Twirl ergonomic win is a typed function you call instead of a stringly
`render('error.html', message=...)`. We capture that with a thin wrapper that
**delegates** to Jinja rather than replacing it:

```python
# generated, opt-in, one per template
def render_error(*, message: str) -> Markup:
    return _env.get_template('error.html.jinja').render(message=message)
```

The responsibilities split cleanly:

- the **wrapper** types the boundary between your Python and the template (calling
  `render_error(mesage=...)` or `render_error(message=123)` is a pyright error)
- the **checker** types the inside of the template (a `{{ mesage }}` typo in the body)
- **Jinja** renders, unchanged

This is the sharpened "phase 2 codegen": a delegating wrapper, not a reimplemented
renderer. It is cheap because we already parse the header the wrapper needs.

### Locked decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Execution model | **Checker** (transpile to a discarded stub) | Zero migration. Jinja renders unchanged. Its own compiler already is the renderer. |
| Type inference | **Delegate to pyright** | We write no inference engine. Loop-variable narrowing, generics, and attribute checks come free. |
| Language | **Python** | Native access to Jinja2's parser (`Environment.parse()`) and the user's own types (`typing.get_type_hints`). Trivial pip / pre-commit distribution. |
| Declaration | **Comment header** (`{#def ... #}`), rung 1 | Self-contained, one line per file, zero coupling. Rung 2 is a later opt-in. |
| v1 checks | Undefined variables + attribute/key access | Undefined vars fall out of pyright's `reportUndefinedVariable`, bad attributes from `reportAttributeAccessIssue`. |

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

The transpiler walks the Jinja AST and emits, for every expression the template uses,
a Python statement that exercises it (`_ = user.name`), preserving nesting so pyright's
scope and narrowing mirror Jinja's. `{% for i in items %}` becomes `for i in items:`,
so pyright infers `i: Item` and checks `{{ i.title }}` for free. Each generated line
carries a `# L<n>` marker back to its template line, and pyright errors are remapped
through those markers. Both undefined variables and bad attributes come from pyright
at zero inference cost, which is the whole point of the checker route.

## Runtime model

One source of truth, the header, drives three opt-in levels. This mirrors how the
project already treats Python: the annotation is written once, a static checker reads
it, and runtime enforcement is a separate opt-in.

- **Level 0, static only (default).** pyright over the stub. Zero runtime cost. Catches
  template-internal errors. This is the whole v1 pitch, and it is the reason people
  install the tool.
- **Level 1, typed call site (opt-in codegen).** The delegating wrapper from
  "Architecture". Still static only, still zero runtime cost. It moves the render call
  from stringly to typed so the boundary is checked by pyright.
- **Level 2, runtime enforcement (opt-in).** The generated wrapper carries real
  annotations, so a runtime validator can check the context at render time. This catches
  what static analysis cannot follow (database rows, API JSON, user input, dynamically
  assembled dicts). Which validator runs is a separate choice (none, beartype, or
  Pydantic), covered in "Types and validators". The tradeoff matches beartype: run it in
  dev and test, or leave it on at boundaries in production because it is cheap.

Two delivery options for Level 2, ship (a) first:

- **(a) Decorate the generated wrappers.** Reuse beartype or Pydantic as-is. No new
  runtime engine to build. Built as a working proof in `examples/runtime`:
  `typed_jinja.wrapper.generate_wrapper(header, name, validator=...)` emits the typed
  function, and `validator='beartype'` decorates it while `validator='pydantic'`
  validates each parameter through a `TypeAdapter` before rendering. Tests confirm
  beartype raises on a wrong type and Pydantic coerces a dict then rejects a bad one.
- **(b) A `TypedEnvironment(jinja2.Environment)`** whose `.render()` reads the header,
  resolves the declared types by evaluating the annotation strings in the header's
  import namespace (the way `get_type_hints` does), validates the context, then
  delegates to normal Jinja rendering.

The framing to hold onto: the header is the annotation, pyright is mypy, and the
runtime validator is the opt-in enforcement of that same annotation. Default off,
because the zero-cost static checker is why people install it.

## Types and validators: two axes

Pydantic is optional on two independent axes, and it is never a hard dependency. The
core works against plain typing with no Pydantic in the required path.

### Axis 1: what the context types are

The header imports and names a type. That type can be a dataclass, a `TypedDict`, a
`Protocol`, a `NamedTuple`, or a Pydantic model. The checker and the wrapper are
agnostic to which. pyright reads Pydantic v2 model fields as ordinary annotated
attributes, so attribute access is checked identically to a dataclass with zero
special-casing. Choosing a Pydantic model buys computed fields, validated invariants,
and `.model_dump()` feeding the `tojson` filter.

### Axis 2: which runtime validator enforces Level 2

- **none**: static only, the default.
- **beartype**: checks the value against the annotation and raises. Near-zero cost.
  Non-transforming, so the object the template receives is the object you passed.
- **Pydantic `TypeAdapter`**: parses and coerces the context into a validated object.
  Heavier. Best when the context comes from JSON, a database, or form input.

Axis 2 is independent of Axis 1.

### The compatibility fact

`pydantic.TypeAdapter` works on any type, not only `BaseModel`. So
`TypeAdapter(SomeDataclass).validate_python(ctx)` validates a dataclass context.
Pydantic-as-validator composes even when the context types are plain dataclasses, and
beartype composes even when the context types are Pydantic models. The axes never lock
each other.

Level 2 wrapper with the Pydantic validator:

```python
from pydantic import TypeAdapter

_ctx = TypeAdapter(User)

def render_profile(*, user: User) -> Markup:
    user = _ctx.validate_python(user)
    return _env.get_template('profile.html.jinja').render(user=user)
```

One honest semantic difference to label in the docs: beartype checks the value and
leaves the object alone, while Pydantic parses and can hand the template a new coerced
object. Parse-mode should be opt-in and labeled "validate and transform" so nobody is
surprised that the rendered object differs from the one they passed.

### Recommendation

The core stays Pydantic-agnostic and works against plain typing. Pydantic is optional on
both axes. beartype is the default Level 2 because it is lighter and non-transforming.
Pydantic is the boundary-parsing upgrade for FastAPI-style apps. Positioning line: bring
your own types (dataclass or Pydantic), bring your own runtime enforcement (none,
beartype, or Pydantic).

## Roadmap and tablestakes staging

| Capability | Stage | Why |
| --- | --- | --- |
| CLI + non-zero exit | v1 | cheap, already built |
| JSON / SARIF output | v1 | the AI-ready and CI story. SARIF plugs into GitHub code scanning and agents. A `--format` flag over data we already have |
| Environment globals declaration | v1 | without it `static_url()` is a false positive. A tool that cries wolf gets uninstalled. Enjoyability blocker |
| Stable rule codes and catalog | v1.1 | agents and humans reference and suppress specific checks |
| LSP (diagnostics in the template) | v1.1 fast-follow | the ergonomic multiplier. A real build (map template-to-stub positions, proxy pyright). CI value lands first via CLI/pre-commit |
| Typed wrapper codegen | v1.1 | the native-callable win, opt-in per file |
| Extension-tag syntax (rung 2) | v1.2+ | only after demand is proven |

v1 is a checker that is quiet (globals), scriptable (JSON/SARIF), and drops into CI
(CLI/pre-commit).

### Status (current build)

- Shipped: the checker (undefined variables plus attribute and item access), the CLI
  with `--format text|json|sarif`, and the Environment globals declaration.
- Shipped as a working proof (ahead of its v1.1 slot): the Level-1 typed wrapper with
  Level-2 beartype and Pydantic enforcement in `examples/runtime`, so the runtime story
  is verified before yak-shears adoption.
- In progress: the LSP spike with Neovim integration, and v1 hardening (a pre-commit
  hook, template-syntax and missing-pyright handling, broader Jinja node coverage).

## Scope

**v1:**
- `{#def ... #}` header parsing (imports + `name: Type` params)
- Transpile: output `{{ }}`, `{% for %}`, `{% if %}/{% elif %}/{% else %}`, `{% set %}`,
  attribute/item access, comparisons, boolean/binary ops, filters (operand checked,
  result untyped)
- pyright invocation + line remapping
- Environment globals declaration (kills the `static_url()` false positive)
- JSON / SARIF output
- CLI `typed-jinja check <paths>` with non-zero exit on errors

**Deferred to v1.1+ (explicit non-goals for now):**
- LSP / editor diagnostics (spike in progress)
- Productizing the typed wrapper codegen (Level 1) and runtime enforcement (Level 2)
  into the CLI and a documented workflow. The mechanism is proven in `examples/runtime`;
  what remains is wiring, not feasibility.
- Extension-tag declaration (rung 2)
- Framework adapters (Flask, Django-Jinja2, FastAPI) that locate "this view renders
  this template with this context"
- Sidecar/registry binding as an alternative to the header
- Macro (`{% macro %}`) arg-count/type checking
- Full filter type signatures, custom extensions, i18n, and `{% include %}` /
  `{% extends %}` / `{% import %}` cross-template context flow
- Non-HTML targets (dbt-style SQL), which are a different program

## Validation targets

1. A tiny standalone example in `examples/` (fastest proof the mechanism works).
2. The user's **yak-shears** project, the real migration test.
3. A demo Django/Flask app as a later, optional showcase. Django's own DTL is not
   Jinja, so a Flask or standalone-Jinja demo is the cleaner first target.

## Validation findings (spike, run against yak-shears)

Ran the spike against real templates in `~/Developer/kyleking/yak-shears/yak_shears/_templates`.
Those templates use `{% extends %}`/`{% block %}` inheritance (26 blocks, 7 extends),
`{% if %}`/`{% for %}`/`{% set %}`, and filters (`length`, `tojson`, `title`, `sort`,
`min`, `max`, `join`, `format`, `default`).

What worked: on `error.html.jinja` (extends `base.html.jinja`, fills `{% block content %}`
with `{{ message }}`), the transpiler skips the inheritance nodes it does not model yet
but still extracts and checks the expressions inside the block. A correct header
(`message: str`) passes clean, and a `mesage` typo is caught at the right line.

Two concrete gaps this surfaced, now pulled into the v1 scope above:

1. **Jinja Environment globals** (`static_url()`, `url_for()`, `get_flashed_messages()`).
   These are injected into `Environment.globals`, not passed per render, so a template
   that calls one gets flagged as an undefined variable (false positive). v1 needs a
   project-level declaration of global names/signatures (a config file or a `{#globals#}`
   header) so the checker treats them as defined. Highest-value fix for Flask and any
   real app.
2. **Inheritance context flow.** A child template's effective context spans the child
   and its base (and any `{% include %}`). v1 checks one file at a time, so variables a
   base template needs are not cross-checked against the child's header. Modeling
   `{% extends %}` / `{% block %}` / `{% include %}` context flow is a v1.1 feature.

## Open questions

- Header ergonomics: does `{#def ... #}` feel right in real templates, or is a sidecar
  preferable? (Decide after using it on yak-shears.)
- pyright dependency: acceptable to require it, or should mypy be a supported backend
  too? (pyright-only for the spike.)
- Globals declaration shape: a `{#globals#}` header per template, or one project-level
  config file that names the Environment globals once? (Lean config file, because
  globals are environment-wide.)
- How to handle `{% include %}` and macro imports without cross-template context flow:
  skip-and-warn for v1.
