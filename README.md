# typed-jinja

Type-check your Jinja2 templates. It is mypy for the context you pass to a template.

## The problem

The variables you hand a Jinja template are untyped. Rename a model field, mistype an
attribute, or forget to pass a variable, and nothing tells you until the template
renders, often in production and often on a page you did not click through. Jinja's own
philosophy keeps the template language loose, so nothing checks that the context matches
what the template expects.

typed-jinja closes that gap without a new template language and without changing how
Jinja renders. You declare the context once, in a comment, and a type checker validates
every variable and attribute the template touches.

## 30-second example

Add a one-line header to a template naming its context:

```jinja
{#def
from myapp.models import User
user: User
#}
<h1>Hello {{ user.naem }}</h1>
{% for item in user.items %}
  <li>{{ item.titel }}</li>
{% endfor %}
```

Run the checker:

```console
$ typed-jinja check templates/
templates/greeting.html:5:14 error: Cannot access attribute "naem" for class "User" (reportAttributeAccessIssue)
templates/greeting.html:8:14 error: Cannot access attribute "titel" for class "Item" (reportAttributeAccessIssue)
```

The `{#def #}` block is a plain Jinja comment, so the template renders exactly as before.
The loop variable is narrowed to its element type, so `item.titel` is caught the same way
`user.naem` is.

## Install

```console
uv add typed-jinja      # or: pip install typed-jinja
```

typed-jinja calls [pyright](https://github.com/microsoft/pyright) to do the type
inference, so pyright needs to be on your PATH.

## How it works

typed-jinja parses the template's AST with Jinja's own parser, transpiles it into a small
Python stub that exercises every expression the template uses, and runs pyright over that
stub. Errors are mapped back to the template's own line and column. The stub is thrown
away. Jinja still compiles and renders the real template unchanged, so there is no runtime
cost and nothing to migrate beyond the one-line header.

Environment globals (for example `static_url` or `url_for`) are declared once in
`pyproject.toml` so the checker treats them as defined:

```toml
[tool.typed_jinja]
imports = ["from collections.abc import Callable"]

[tool.typed_jinja.globals]
static_url = "Callable[[str], str]"
```

## Runtime checking (optional)

Static checking is the default and costs nothing at runtime. When you also want to
validate the context at render time, for example when it comes from a database or an API,
typed-jinja can generate a typed wrapper around a template and enforce the types with
[beartype](https://github.com/beartype/beartype) or
[Pydantic](https://github.com/pydantic/pydantic):

```python
from beartype import beartype

@beartype
def render_profile(*, profile: Profile) -> Markup:
    return Markup(env.get_template('profile.html.jinja').render(profile=profile))
```

Now `render_profile(porfile=...)` is a static error at the call site, and a wrong-typed
`profile` raises at runtime. beartype checks and leaves the object alone. Pydantic's
`TypeAdapter` instead parses and coerces, which is useful at a data boundary. Both work
whether your context types are dataclasses or Pydantic models. A runnable proof lives in
`examples/runtime`. The header is the annotation, pyright is the static checker, and
beartype or Pydantic is the opt-in runtime enforcement of that same annotation.

## CI and agents

`typed-jinja check --format json` and `--format sarif` emit machine-readable output. The
SARIF report plugs into GitHub code scanning and coding agents, so template type errors
show up next to your other findings.

## Status

Early and moving. The checker, the CLI with JSON and SARIF output, the globals
declaration, and the runtime-wrapper proof are in place. The LSP (in-editor diagnostics)
and v1 hardening are in progress. See [PLAN.md](PLAN.md) for the architecture, the
roadmap, and the design decisions behind all of this.
