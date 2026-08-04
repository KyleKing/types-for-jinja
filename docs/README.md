# types-for-jinja

Type-check your Jinja2 templates. `types-for-jinja` is mypy for the context you pass to a template: declare the context once, in a comment, and pyright validates every variable and attribute the template touches. There is no new template language, Jinja renders unchanged, and there is no runtime cost by default.

`types-for-jinja` is deliberately narrow (Jinja2 plus the dialects Jinja's own parser reads). If your needs differ, there are alternatives to consider:

- [TypeJinja](https://dl.acm.org/doi/10.1145/3786583.3786905) type-checks dbt's Jinja against dbt's own IR and ships with the dbt fusion engine, so use it for dbt projects
- [templ](https://github.com/a-h/templ) (Go), [askama](https://github.com/askama-rs/askama) (Rust), and [Twirl](https://github.com/playframework/twirl) (Scala) compile templates into typed host-language functions, the ergonomic model this project borrows
- [JinjaX](https://github.com/jpsca/jinjax) adds component syntax to Jinja (the `{#def #}` header comes from JinjaX) and composes with `types-for-jinja` rather than replacing it
- [djlint](https://github.com/djlint/djLint) lints and formats template style rather than types, so it runs alongside rather than instead

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
$ types-for-jinja check templates/
templates/greeting.html:5:14 error: Cannot access attribute "naem" for class "User" (reportAttributeAccessIssue)
templates/greeting.html:8:14 error: Cannot access attribute "titel" for class "Item" (reportAttributeAccessIssue)
```

The `{#def #}` block is a plain Jinja comment, so the template renders exactly as before. The loop variable is narrowed to its element type, so `item.titel` is caught the same way `user.naem` is.

A macro takes its own `{#def #}` block, which types its parameters for both its body and its callers, across files:

```jinja
{% macro field(label, value) %}
  {#def
  label: str
  value: str
  #}
  <label>{{ label }}</label><span>{{ value }}</span>
{% endmacro %}
```

Without that block the parameters stay untyped and only arity is checked.

## Installation

```console
uv add types-for-jinja      # or: pip install types-for-jinja
```

`types-for-jinja` calls [pyright](https://github.com/microsoft/pyright) for the type inference, so pyright needs to be on your PATH.

## How it works

`types-for-jinja` parses the template with Jinja's own parser, transpiles it into a small Python stub that exercises every expression, and runs pyright over that stub. Errors map back to the template's own line and column. The stub is thrown away and Jinja renders the real template unchanged, so there is nothing to migrate beyond the one-line header. Declare Environment globals (such as `static_url`) once under `[tool.types_for_jinja]` in `pyproject.toml` so the checker treats them as defined.

`types-for-jinja check --format json` and `--format sarif` emit machine-readable output for CI. The SARIF report plugs into GitHub code scanning and coding agents. A pre-commit hook and an LSP (with a Neovim integration in `editors/nvim`) deliver the same diagnostics to commits and editors.

## Typed render calls (optional)

`check` types the inside of a template. `types-for-jinja wrapper` types the call site, so `render_profile(porfile=...)` fails pyright the same way a typo in the template body does:

```console
$ types-for-jinja wrapper templates/ -o myapp/_render \
    --env-import 'from myapp.templating import env as _env'
types-for-jinja: Wrote 3 of 3 wrapper file(s)
```

Each template gets one function whose signature is its `{#def #}` header, and whose body calls Jinja unchanged:

```python
@beartype
def render_profile(*, profile: Profile) -> Markup:
    """Render profile.html.jinja with a checked context."""
    return Markup(_env.get_template('profile.html.jinja').render(profile=profile))
```

Set the options once in `pyproject.toml` instead of passing them every run:

```toml
[tool.types_for_jinja]
template_dirs = ["myapp/templates"]

[tool.types_for_jinja.wrapper]
env_import = "from myapp.templating import env as _env"
out_dir = "myapp/_render"
validator = "beartype"
```

`template_dirs` is what makes the generated `get_template()` argument match the name your loader uses. Run `types-for-jinja wrapper --check` in CI or a pre-commit hook to fail when a generated wrapper no longer matches its template.

Web apps usually return a response rather than `Markup`. Point `--return-type` and `--return-import` (or `return_type` and `return_import` in the config) at your framework's class and the wrapper calls it instead:

```python
def render_profile(*, profile: Profile) -> HTMLResponse:
    """Render profile.html.jinja with a checked context."""
    return HTMLResponse(_env.get_template('profile.html.jinja').render(profile=profile))
```

A helper that does real work before rendering, or sets a status code, stays hand-written and calls the generated function for the render itself.

### Runtime checking

`--validator` adds render-time enforcement on top: [beartype](https://github.com/beartype/beartype) checks the value against the annotation and raises, [Pydantic](https://github.com/pydantic/pydantic) parses and coerces it through a `TypeAdapter`. Both work whether your context types are dataclasses or Pydantic models. The default is `none`, because the static check costs nothing at runtime. Pydantic can hand the template a new coerced object, so the value you pass is not always the value rendered; beartype leaves the object alone. A runnable proof of both lives in `examples/runtime`.

## Scope

`types-for-jinja` checks anything Jinja's own parser reads: plain Jinja2, JinjaX, and the templates in Flask, Litestar, FastAPI, Copier, and Cookiecutter projects, as long as the standard delimiters are kept. Out of scope on purpose: Ansible, Salt, and dbt (untyped runtime contexts and large custom filter libraries, and dbt already has TypeJinja), engines not hosted in Python (Nunjucks, Twig, Liquid, Handlebars), and Python engines with different lookup semantics (Django's DTL, Mako, Chameleon). See [PLAN] for the reasoning.

## Project Status

Early and moving. See [PLAN] for the architecture, roadmap, and design decisions, plus the `Open Issues` and the [CODE_TAG_SUMMARY]. For release history, see the [CHANGELOG].

## Contributing

We welcome pull requests! For your pull request to be accepted smoothly, we suggest that you first open a GitHub issue to discuss your idea. For resources on getting started with the code base, see the below documentation:

- [DEVELOPER_GUIDE]
- [STYLE_GUIDE]

## Code of Conduct

We follow the [Contributor Covenant Code of Conduct][contributor-covenant].

### Open Source Status

We try to reasonably meet most aspects of the "OpenSSF scorecard" from [Open Source Insights](https://deps.dev/pypi/types-for-jinja)

## Responsible Disclosure

If you have any security issue to report, please contact the project maintainers privately. You can reach us at [dev.act.kyle@gmail.com](mailto:dev.act.kyle@gmail.com).

## License

[LICENSE]

[changelog]: https://types-for-jinja.kyleking.me/docs/CHANGELOG
[code_tag_summary]: https://types-for-jinja.kyleking.me/docs/CODE_TAG_SUMMARY
[contributor-covenant]: https://www.contributor-covenant.org
[developer_guide]: https://types-for-jinja.kyleking.me/docs/DEVELOPER_GUIDE
[license]: https://github.com/kyleking/types-for-jinja/blob/main/LICENSE
[plan]: https://github.com/kyleking/types-for-jinja/blob/main/PLAN.md
[style_guide]: https://types-for-jinja.kyleking.me/docs/STYLE_GUIDE
