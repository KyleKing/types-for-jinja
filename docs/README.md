# typed-jinja

Type-check your Jinja2 templates. It is mypy for the context you pass to a template.

## The problem

The variables you hand a Jinja template are untyped. Rename a model field, mistype an attribute, or forget to pass a variable, and nothing tells you until the template renders, often in production. typed-jinja closes that gap without a new template language and without changing how Jinja renders. You declare the context once, in a comment, and a type checker validates every variable and attribute the template touches.

## 30-second example

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

```console
$ typed-jinja check templates/
templates/greeting.html:5:14 error: Cannot access attribute "naem" for class "User" (reportAttributeAccessIssue)
templates/greeting.html:8:14 error: Cannot access attribute "titel" for class "Item" (reportAttributeAccessIssue)
```

The `{#def #}` block is a plain Jinja comment, so the template renders exactly as before. The loop variable is narrowed to its element type, so `item.titel` is caught too.

## Installation

```console
uv add typed-jinja      # or: pip install typed-jinja
```

typed-jinja calls [pyright](https://github.com/microsoft/pyright) for the type inference, so pyright needs to be on your PATH.

## How it works

typed-jinja parses the template with Jinja's own parser, transpiles it into a small Python stub that exercises every expression, and runs pyright over that stub. Errors map back to the template's own line and column. The stub is thrown away and Jinja renders the real template unchanged, so there is no runtime cost and nothing to migrate beyond the one-line header. Declare Environment globals (such as `static_url`) once under `[tool.typed_jinja]` in `pyproject.toml` so the checker treats them as defined.

## Runtime checking (optional)

Static checking is the default and costs nothing at runtime. To also validate the context at render time, typed-jinja can generate a typed wrapper and enforce the types with [beartype](https://github.com/beartype/beartype) (check) or [Pydantic](https://github.com/pydantic/pydantic) (parse and coerce). Both work whether your context types are dataclasses or Pydantic models. A runnable proof lives in `examples/runtime`.

## CI and agents

`typed-jinja check --format json` and `--format sarif` emit machine-readable output. The SARIF report plugs into GitHub code scanning and coding agents.

## Project Status

Early and moving. See [PLAN] for the architecture, roadmap, and design decisions, plus the `Open Issues` and the [CODE_TAG_SUMMARY]. For release history, see the [CHANGELOG].

## Contributing

We welcome pull requests! For your pull request to be accepted smoothly, we suggest that you first open a GitHub issue to discuss your idea. For resources on getting started with the code base, see the below documentation:

- [DEVELOPER_GUIDE]
- [STYLE_GUIDE]

## Code of Conduct

We follow the [Contributor Covenant Code of Conduct][contributor-covenant].

### Open Source Status

We try to reasonably meet most aspects of the "OpenSSF scorecard" from [Open Source Insights](https://deps.dev/pypi/typed-jinja)

## Responsible Disclosure

If you have any security issue to report, please contact the project maintainers privately. You can reach us at [dev.act.kyle@gmail.com](mailto:dev.act.kyle@gmail.com).

## License

[LICENSE]

[changelog]: https://typed-jinja.kyleking.me/docs/CHANGELOG
[code_tag_summary]: https://typed-jinja.kyleking.me/docs/CODE_TAG_SUMMARY
[contributor-covenant]: https://www.contributor-covenant.org
[developer_guide]: https://typed-jinja.kyleking.me/docs/DEVELOPER_GUIDE
[license]: https://github.com/kyleking/typed-jinja/blob/main/LICENSE
[plan]: https://github.com/kyleking/typed-jinja/blob/main/PLAN.md
[style_guide]: https://typed-jinja.kyleking.me/docs/STYLE_GUIDE
