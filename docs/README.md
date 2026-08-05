# types-for-jinja

A mostly invisible type checking and LSP extension for Jinja, JinjaX, and
similar templates, built on the pyright, ty, or mypy you already run.
Declare a template's context once, in a comment, and `types-for-jinja generate`
writes a line-aligned Python stub for it.
Your checker then reports every bad variable and attribute the template touches,
at the template's own line, in the same run that checks the rest of your code.
In the editor, the same stubs feed your Python language server, so templates get
inline diagnostics, completion, and hover without a second toolchain.
There is no new template language, Jinja renders unchanged, and nothing runs at
render time by default.

The only dependency is jinja2.
types-for-jinja never invokes a type checker itself, so template checks run
under your checker, your version, and your configuration, including checker
plugins such as the mypy pydantic plugin.
The "mostly" in invisible is raw CI output naming the stub instead of the
template; `types-for-jinja remap` and the editor mirror close that gap, and
"Limitations" lists the rest.

`types-for-jinja` is deliberately narrow (Jinja2 plus the dialects Jinja's own
parser reads).
If your needs differ, there are alternatives to consider:

- [TypeJinja](https://dl.acm.org/doi/10.1145/3786583.3786905) type-checks dbt's
    Jinja against dbt's own IR and ships with the dbt fusion engine, so use it for
    dbt projects
- [templ](https://github.com/a-h/templ) (Go),
    [askama](https://github.com/askama-rs/askama) (Rust), and
    [Twirl](https://github.com/playframework/twirl) (Scala) compile templates into
    typed host-language functions, the ergonomic model this project borrows
- [JinjaX](https://github.com/jpsca/jinjax) adds component syntax to Jinja (the
    `{#def #}` header comes from JinjaX) and composes with `types-for-jinja` rather
    than replacing it
- [djlint](https://github.com/djlint/djLint) lints and formats template style
    rather than types, so it runs alongside rather than instead

## 30-second example

Add a header to a template naming its context:

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

Generate the stubs, then run whichever checker the project already uses:

```console
$ types-for-jinja generate templates/    # or just `generate`, with template_dirs set
types-for-jinja: Wrote 5 file(s) for 1 template(s)
$ ty check
_jinja_stubs/templates/greeting_html.py:5:5: error[unresolved-attribute] Object of type `User` has no attribute `naem`
_jinja_stubs/templates/greeting_html.py:7:9: error[unresolved-attribute] Object of type `Item` has no attribute `titel`
Found 2 diagnostics
```

Generated line N is template line N, so the line numbers are the template's own.
Pipe through `remap` when you want the template's path and column too:

```console
$ ty check | types-for-jinja remap
templates/greeting.html:5:14: error[unresolved-attribute] Object of type `User` has no attribute `naem`
templates/greeting.html:7:10: error[unresolved-attribute] Object of type `Item` has no attribute `titel`
Found 2 diagnostics
```

A pipeline hands back the filter's exit code rather than the checker's, so in CI
let `remap` run the checker instead.
It exits with the checker's status, and with ty's default format the source
excerpt becomes the template's own line:

```console
$ types-for-jinja remap -- ty check
error[unresolved-attribute]: Object of type `User` has no attribute `naem`
 --> templates/greeting.html:5:14
  |
5 | <h1>Hello {{ user.naem }}</h1>
  |              ^^^^^^^^^
  |
```

`remap` reads text output from ty, mypy, and pyright, plus `pyright
--outputjson`, `mypy --output json`, and ty's `gitlab` and `github` formats.
A path outside the stub tree passes through untouched, so piping a whole-project
run leaves the project's own diagnostics exactly as the checker wrote them.

The `{#def #}` block is a plain Jinja comment, so the template renders exactly
as before.
The loop variable is narrowed to its element type, so `item.titel` is caught the
same way `user.naem` is.

A macro takes its own `{#def #}` block, which types its parameters for both its
body and its callers, across files:

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

JinjaX writes the whole context on one line, with commas between, defaults
allowed, and untyped names allowed.
Both spellings parse, and they can be mixed:

```jinja
{#def action, method: str = "post", count: int = 0 #}
```

A name with no annotation is `Any`, so it is declared without being constrained.
A default is carried into the generated wrapper's signature, so callers do not
have to repeat it.

JinjaX component tags are checked against the component's own header.
Point `template_dirs` at the component directory and a use is validated for
missing required attributes and for attribute types:

```jinja
{#def title: str, count: int = 0 #}   <!-- components/Card.jinja -->

<Card count={{ user.name }} class="wide" />
```

```console
$ types-for-jinja remap -- ty check
templates/page.html.jinja:6:16: error[missing-argument] No argument provided for required parameter `title`
templates/page.html.jinja:6:7: error[invalid-argument-type] Expected `int`, found `str`
```

An attribute the component does not declare is not an error, because JinjaX
forwards it to the component as `attrs`, which is what `class="wide"` above
relies on.

A tag an extension adds does not parse until the extension is loaded, and an
unparseable template is skipped entirely, so its own errors go unreported too.
Declaring the extension is what makes the rest of the template checkable:

```toml
[tool.types_for_jinja]
extensions = ["do", "i18n", "loopcontrols"]
```

`i18n` also declares the names it injects (`_`, `gettext`, `ngettext`,
`pgettext`, `npgettext`), so a template using them needs nothing else.
Jinja's own globals (`namespace`, `cycler`, `joiner`, `lipsum`) are declared
automatically when a template names one, including the `{% set ns.total = ...
%}` form.

Jinja's built-in filters carry their return type, so a filtered expression is
still checked:
`{{ items | length }}` is an `int`, and `{% for x in items | sort %}` still
knows what `x` is.
Only the return type is pinned, because a filter catalog that guesses at
argument types reports errors on correct templates.
A filter the catalog does not know (yours, or one from an extension) falls back
to `Any`.

## Installation

```console
uv add types-for-jinja      # or: pip install types-for-jinja
```

That installs jinja2 and nothing else.
Bring your own checker:
pyright, ty, and mypy are each verified against the generated stubs on every CI
run, and anything that reads standard Python annotations should work the same
way.

## How it works

`types-for-jinja generate` parses each template with Jinja's own parser and
writes a small Python module that exercises every expression the template uses,
preserving nesting so your checker's scoping and narrowing mirror Jinja's.
`{% for item in items %}` becomes a real `for` loop, so the checker infers the
element type.
The stub tree mirrors the template tree under `_jinja_stubs/` (only the filename
is mangled, because a module name cannot carry a template extension), and a
manifest maps each stub back to its template.
Environment globals such as `static_url` are declared once under
`[tool.types_for_jinja]` in `pyproject.toml` so they never show up as undefined.

Add `_jinja_stubs/` to `.gitignore` and generate the stubs as a step in
pre-commit or CI rather than committing them; a generated tree does not belong
in the diff.
`types-for-jinja generate --check` fails when a stub is missing or out of
date, and the shipped pre-commit hook runs exactly that check.

If you rename `out_dir`, keep it clear of a leading dot.
Pyright excludes dot-prefixed directories by default, so a hidden stub tree
would sit outside every check pyright runs.

Cross-file constructs resolve at generation time:
a child checks against its whole `{% extends %}` chain, an `{% include %}` body
checks against the including template's context, and `{% import %}`-ed macros
carry their own `{#def #}` types to their callers.

## In your editor

The stubs are ordinary workspace Python, so the Python language server you
already run flags them with no setup:
open the stub and the error is on the same line number as the template.
Two layers make that invisible:

- The `types-for-jinja-lsp` server (the `lsp` extra) attaches to template buffers
    and regenerates the stub as you type, debounced, so your Python checker
    re-checks it live before you save.
    It also completes and describes the typed context in the template itself:
    the names visible at the cursor, the members of their types after a `.`,
    built-in filters after `|` (with return types), tests after `is`, and tags after
    `{%`, plus hover for all of them.
- A thin mirror republishes the stub's diagnostics onto the template buffer, line
    for line, so errors appear inline in the template with your checker's own codes.
    Mirroring has to live in the editor, because one language server cannot read
    another server's diagnostics.
    `editors/nvim` ships it for Neovim.
    VS Code, Cursor, Zed, and Helix need the same layer against their own diagnostic
    APIs, and none of that is built.

Attribute completion asks a Python language server what the expression's type
offers, taking the first of pyright, basedpyright, `ty server`, pylsp, or jedi
found on `PATH`.
Pin one with `[tool.types_for_jinja] language_server` if you run several.
When none is installed, member completion is simply absent and everything else
still works.

## Configuration

Everything lives under `[tool.types_for_jinja]` in `pyproject.toml`, and every
setting has a working default.

| Setting           | Default                     | What it does                                                                                                                                                   |
| ----------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `globals`         | none                        | Names your `Environment.globals` injects, as a `name = "Type"` table, so `static_url()` is not a false positive                                                |
| `imports`         | none                        | Import lines the generated stubs need to resolve the types named in `globals`                                                                                  |
| `out_dir`         | `_jinja_stubs`              | Where stubs go. Rejected unless every path segment is an identifier, since the stubs import each other relatively                                              |
| `suppression`     | `portable`                  | Which ignore comment `{# type: ignore #}` becomes: `portable`, `mypy`, `pyright`, or `ty`                                                                      |
| `template_dirs`   | none                        | Where `{% extends %}`, `{% include %}`, and `{% import %}` are resolved from, and what `generate` searches when given no paths. Accepts `package:subdirectory` |
| `template_globs`  | `*.html`, `*.jinja`, `*.j2` | Patterns a directory argument is searched for                                                                                                                  |
| `language_server` | first found                 | Pins the language server attribute completion asks, instead of taking the first on `PATH`                                                                      |
| `extensions`      | none                        | jinja2 extensions to load so their tags parse: `debug`, `do`, `i18n`, `loopcontrols`                                                                           |
| `syntax`          | Jinja's own                 | Delimiters, using `jinja2.Environment`'s own keyword names                                                                                                     |
| `wrapper`         | see below                   | Options for `types-for-jinja wrapper`                                                                                                                          |

```toml
[tool.types_for_jinja]
imports = ["from collections.abc import Callable"]
template_dirs = ["myapp:templates"]

[tool.types_for_jinja.globals]
static_url = "Callable[[str], str]"
current_route = "str"
```

## Suppressing a diagnostic

An inline `{# type: ignore #}` in the template becomes a blanket ignore comment
on the generated line.
Checkers spell that differently, so name yours if you run only one:

```toml
[tool.types_for_jinja]
suppression = "ty" # portable (default), mypy, pyright, or ty
```

The default emits `# type: ignore`, which pyright, ty, and mypy all honour.
Naming a checker emits only what that checker reads, so `pyright` writes `#
pyright: ignore` and mypy will not honour it.
Suppression is blanket per line rather than per code, because rule codes differ
between checkers and a wrong one fails to suppress.

## Typed render calls (optional)

`generate` types the inside of a template.
`types-for-jinja wrapper` types the call site, so `render_profile(porfile=...)`
fails your checker the same way a typo in the template body does:

```console
$ types-for-jinja wrapper templates/ -o myapp/_render \
    --env-import 'from myapp.templating import env as _env'
types-for-jinja: Wrote 3 of 3 wrapper file(s)
```

Each template gets one function whose signature is its `{#def #}` header, and
whose body calls Jinja unchanged:

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

`template_dirs` is what makes the generated `get_template()` argument match the
name your loader uses.
Run `types-for-jinja wrapper --check` in CI or a pre-commit hook to fail when a
generated wrapper no longer matches its template.

Web apps usually return a response rather than `Markup`.
Point `--return-type` and `--return-import` (or `return_type` and
`return_import` in the config) at your framework's class and the wrapper calls
it instead:

```python
def render_profile(*, profile: Profile) -> HTMLResponse:
    """Render profile.html.jinja with a checked context."""
    return HTMLResponse(_env.get_template('profile.html.jinja').render(profile=profile))
```

A helper that does real work before rendering, or sets a status code, stays
hand-written and calls the generated function for the render itself.

### Runtime checking

`--validator` adds render-time enforcement on top:
[beartype](https://github.com/beartype/beartype) checks the value against the
annotation and raises, [Pydantic](https://github.com/pydantic/pydantic) parses
and coerces it through a `TypeAdapter`.
Both work whether your context types are dataclasses or Pydantic models.
The default is `none`, because the static check costs nothing at runtime.
Pydantic can hand the template a new coerced object, so the value you pass is
not always the value rendered; beartype leaves the object alone.
A runnable proof of both lives in `examples/runtime`.

## Scope

`types-for-jinja` checks anything Jinja's own parser reads:
plain Jinja2, JinjaX, and the templates in Flask, Litestar, FastAPI, Copier, and
Cookiecutter projects.
A superset that changes Jinja's delimiters declares them once, using the same
names `jinja2.Environment` uses:

```toml
[tool.types_for_jinja.syntax]
variable_start_string = "[["
variable_end_string = "]]"
```

Copier and Cookiecutter put Jinja expressions in directory names.
A stub tree mangles a directory name that is not already a valid identifier, so
`template/{{ module_name }}/__init__.py.jinja` is checkable and still reported
at its real path.
Set `template_globs` when the templates are not `.html`, `.jinja`, or `.j2`:

```toml
[tool.types_for_jinja]
template_dirs = ["{{cookiecutter.project_slug}}"]
template_globs = ["*.md", "*.py", "*.toml"]
```

Templates shipped inside an installed package (what `jinja2.PackageLoader`
loads) are reachable with a `package:subdirectory` entry in `template_dirs`,
alongside plain paths:

```toml
[tool.types_for_jinja]
template_dirs = ["myapp:templates", "local/templates"]
```

Out of scope on purpose:
Ansible, Salt, and dbt (untyped runtime contexts and large custom filter
libraries, and dbt already has TypeJinja), engines not hosted in Python
(Nunjucks, Twig, Liquid, Handlebars), and Python engines with different lookup
semantics (Django's DTL, Mako, Chameleon).
[DESIGN] gives the reasoning for each.

## Limitations

- Raw checker output names the stub, not the template.
    The line number is the template's own, and the stub tree mirrors the template
    tree, so the mapping reads at a glance; `remap` recovers the path and column for
    CI logs, and the editor mirror recovers them inline.
    Python has no equivalent of Go's `//line` directive, which is why the path
    cannot be fixed at the source.
- Stubs must be regenerated when templates change.
    `generate --check` in pre-commit or CI catches a stale one; the LSP regenerates
    on edit.
- A template with no line-aligned form (rare; measured under 3% on real template
    sets) falls back to `# L<n>` markers, which `remap` and the mirror still read,
    and raw checker output does not.
- Filter and test argument types are unchecked; only built-in return types are
    pinned, and unknown filters widen to `Any`.
- A JinjaX component tag that cannot be resolved to a file is skipped, which
    includes any tag carrying a catalog prefix (`<ui:Button />`), because the prefix
    maps to a search path that lives in the catalog rather than in the template.
- Only jinja2's own extensions can be declared.
    A project-defined extension would mean importing project code to parse a
    template, and a custom tag's meaning is not inferable from its parser hook, so
    those templates are skipped with a warning.
- Templates that exist only behind a `DictLoader` or a database still need a copy
    on disk to be checked.

## Project Status

Early and moving.
[DESIGN] holds the settled decisions, the scope boundary, and the measurements
they rest on; [BLUE_SKY] holds unscheduled work and why each item is waiting.
See also the `Open Issues` and the [CODE_TAG_SUMMARY].
For release history, see the [CHANGELOG].

## Contributing

We welcome pull requests!
For your pull request to be accepted smoothly, we suggest that you first open a
GitHub issue to discuss your idea.
For resources on getting started with the code base, see the below
documentation:

- [DEVELOPER_GUIDE]
- [STYLE_GUIDE]

## Code of Conduct

We follow the [Contributor Covenant Code of Conduct][contributor-covenant].

### Open Source Status

We try to reasonably meet most aspects of the "OpenSSF scorecard" from
[Open Source Insights](https://deps.dev/pypi/types-for-jinja)

## Responsible Disclosure

If you have any security issue to report, please contact the project maintainers
privately.
You can reach us at [dev.act.kyle@gmail.com](mailto:dev.act.kyle@gmail.com).

## License

[LICENSE]

[blue_sky]: https://github.com/kyleking/types-for-jinja/blob/main/docs/BLUE_SKY.md
[changelog]: https://types-for-jinja.kyleking.me/docs/CHANGELOG
[code_tag_summary]: https://types-for-jinja.kyleking.me/docs/CODE_TAG_SUMMARY
[contributor-covenant]: https://www.contributor-covenant.org
[design]: https://github.com/kyleking/types-for-jinja/blob/main/docs/DESIGN.md
[developer_guide]: https://types-for-jinja.kyleking.me/docs/DEVELOPER_GUIDE
[license]: https://github.com/kyleking/types-for-jinja/blob/main/LICENSE
[style_guide]: https://types-for-jinja.kyleking.me/docs/STYLE_GUIDE
