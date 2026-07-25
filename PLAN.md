# typed-jinja — implementation plan

A static type checker for Jinja2 templates. It validates the variables, attribute
access, and control flow inside a template against a typed context you declare, with
no new template language and no runtime cost.

## Origin

Distilled from research (see the "Python templating libraries with type support"
chat). Python has no equivalent of Go's templ, Scala's Twirl, or Rust's askama:
a template whose context is checked against real host-language types before it runs.
Prior art that shaped the design:

- **dbt TypeJinja** (2025) — a static checker over dbt's Jinja IR that found 30 real,
  previously-unknown type errors. Proves the demand and the technique.
- **Twirl / templ / askama** — compile a template into a typed host-language function,
  wired into the build. Durable for 10+ years. This is the model we follow.
- **Coffin / Jingo** (dead Django-Jinja shims) — the anti-pattern: a dual-engine
  compatibility layer dies once the host framework absorbs the capability. We do not
  build a shim.

## Decisions (locked with the user)

| Decision | Choice | Why |
| --- | --- | --- |
| Architecture | **Codegen-first** (Twirl/templ model) | Transpile the template to a typed Python function; let **pyright** do the type inference. We write no inference engine. Loop-variable narrowing, generics, and attribute checks come free from pyright. |
| Language | **Python** | Native access to Jinja2's parser (`Environment.parse()`) and the user's own types (`typing.get_type_hints`). Trivial pip / pre-commit distribution. |
| Type binding | **In-template header comment** (`{#def ... #}`) | Twirl's first-line param declaration, adapted to a Jinja comment so the template stays valid and renders nothing. Self-contained, one line per file. |
| v1 checks | Undefined variables + attribute/key access | The non-negotiable core. Undefined vars fall out of pyright's `reportUndefinedVariable`; bad attributes from `reportAttributeAccessIssue`. |
| Distribution | CLI + pre-commit | Enough to drop into a real workflow. |

## How it works

```
template.html ──parse header──► param signature
      │
      └──env.parse()──► Jinja AST ──transpile──► generated Python function
                                                        │
                                          pyright --outputjson
                                                        │
                                   map generated-line errors ──► template:line diagnostics
```

The transpiler walks the Jinja AST and emits, for every expression the template uses,
a Python statement that exercises it (`_ = user.name`), preserving nesting so pyright's
scope and narrowing mirror Jinja's. `{% for i in items %}` becomes `for i in items:`,
so pyright infers `i: Item` and checks `{{ i.title }}` for free. Each generated line
carries a `# L<n>` marker back to its template line; pyright errors are remapped through
those markers.

Undefined variable and bad attribute both come from pyright at zero inference cost —
that is the whole point of codegen-first.

## Scope

**v1 (this spike):**
- `{#def ... #}` header parsing (imports + `name: Type` params)
- Transpile: output `{{ }}`, `{% for %}`, `{% if %}/{% elif %}/{% else %}`, `{% set %}`,
  attribute/item access, comparisons, boolean/binary ops, filters (operand checked,
  result untyped)
- pyright invocation + line remapping
- CLI `typed-jinja check <paths>` with non-zero exit on errors

**Deferred to v1.1+ (explicit non-goals for now):**
- Pydantic adapter (core works against dataclass / TypedDict / Protocol; Pydantic is
  just another typed context, no special-casing needed for the spike)
- LSP / editor diagnostics
- Framework adapters (Flask, Django-Jinja2, FastAPI) that locate "this view renders
  this template with this context"
- Sidecar/registry binding as an alternative to the header
- Macro (`{% macro %}`) arg-count/type checking
- Full filter type signatures, custom extensions, i18n, `{% include %}`/`{% import %}`
  cross-template context flow
- Non-HTML targets (dbt-style SQL) — a different program

## Validation targets

1. A tiny standalone example in `examples/` (fastest proof the mechanism works).
2. The user's **yak-shears** project, if it uses Jinja2 — the real migration test.
3. A demo Django/Flask app is a later, optional showcase; note that Django's own DTL is
   not Jinja, so a Flask or standalone-Jinja demo is the cleaner first target.

## Validation findings (spike, run against yak-shears)

Ran the spike against real templates in `~/Developer/kyleking/yak-shears/yak_shears/_templates`.
Those templates use `{% extends %}`/`{% block %}` inheritance (26 blocks, 7 extends),
`{% if %}`/`{% for %}`/`{% set %}`, and filters (`length`, `tojson`, `title`, `sort`,
`min`, `max`, `join`, `format`, `default`).

What worked: on `error.html.jinja` (extends `base.html.jinja`, fills `{% block content %}`
with `{{ message }}`), the transpiler skips the inheritance nodes it does not model yet but
still extracts and checks the expressions inside the block. Correct header (`message: str`)
passes clean; a `mesage` typo is caught at the right line.

Two concrete gaps this surfaced, now the top v1.1 priorities:

1. **Jinja Environment globals** (`static_url()`, `url_for()`, `get_flashed_messages()`).
   These are injected into the `Environment.globals`, not passed per render, so a template
   that calls one would be flagged as an undefined variable (false positive). v1 needs a
   project-level declaration of global names/signatures (a config file or a `{#globals#}`
   header) so the checker treats them as defined. This is the highest-value fix for Flask
   and any real app.
2. **Inheritance context flow.** A child template's effective context spans both the child
   and its base (and any `{% include %}`). v1 checks one file at a time, so variables a base
   template needs are not cross-checked against the child's header. Modeling `{% extends %}`
   / `{% block %}` / `{% include %}` context flow is a real v1.1 feature.

## Open questions

- Header ergonomics — does `{#def ... #}` feel right in real templates, or is a sidecar
  preferable? (Decide after using it on yak-shears.)
- pyright dependency — acceptable to require it, or should mypy be a supported backend
  too? (pyright-only for the spike.)
- How to handle `{% include %}` / macro imports without cross-template context flow —
  skip-and-warn for v1.
