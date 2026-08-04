# Remaining work

Settled decisions, the scope boundary, and the measurements behind them are in [docs/DESIGN.md](./docs/DESIGN.md). Unscheduled items are in [docs/BLUE_SKY.md](./docs/BLUE_SKY.md). What follows is work that will happen, in order.

## JinjaX and jinja-adjacent coverage

JinjaX is where the `{#def #}` header comes from, so its templates should check without translation. Gaps, in priority order:

1. **Header defaults and the one-line form.** JinjaX writes `{#def action, method: str = "post" #}`: comma-separated, defaults allowed, untyped names allowed. `header.py` is line-based and reports `str = "post"` as a malformed annotation. Parse defaults (the wrapper signature carries them), accept the comma-separated form beside the line-per-entry form, and type a bare name as `Any`.
1. **Component tags.** `<Card title={{ x }} />` is JinjaX preprocessor syntax. Jinja's parser reads it as literal text plus output nodes, so the embedded `{{ x }}` is checked today and the component boundary is not. The aligned-stub answer: scan text nodes for PascalCase tags, resolve `Card` to its component template, and emit the use as a call against a signature generated from that component's own `{#def #}`. The user's checker then validates attribute names, types, and required-versus-defaulted, with no dependency on jinjax itself.
1. **`{#css#}` and `{#js#}` blocks** parse as comments and are ignored, which is correct. Nothing to do; recorded so the question stays settled.

Beyond JinjaX:

1. **Extension tags.** `{% trans %}`, `{% do %}`, and `{% break %}` fail `Environment.parse` when the extension is not loaded, so those templates are skipped today. Add `[tool.types_for_jinja] extensions = [...]`, loaded into the parsing Environment. The stock extensions ship inside jinja2, so the dependency list is unchanged. Enabling i18n also injects `_`, `gettext`, and `ngettext` as known globals.
1. **`namespace()`.** `{% set ns.count = 1 %}` currently skips the whole template. Model `namespace` as a known global whose result accepts any attribute, so the rest of the template still checks.
1. **Discovery.** `_iter_templates` globs only `*.html` and `*.jinja`. Add `*.j2`, a `template_globs` setting, and a fallback to `template_dirs` when no paths are given.
1. **Copier and Cookiecutter** need only what exists: configured delimiters, `template_dirs`, and declared globals. Confirm that with an integration test over a realistic layout of each.
