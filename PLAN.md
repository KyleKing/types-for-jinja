# Remaining work

Settled decisions, the scope boundary, and the measurements behind them are in [docs/DESIGN.md](./docs/DESIGN.md). Unscheduled items are in [docs/BLUE_SKY.md](./docs/BLUE_SKY.md). What follows is work that will happen, in order.

## JinjaX and jinja-adjacent coverage

JinjaX is where the `{#def #}` header comes from, so its templates should check without translation. Gaps, in priority order:

1. **`{#css#}` and `{#js#}` blocks** parse as comments and are ignored, which is correct. Nothing to do; recorded so the question stays settled.

Beyond JinjaX:

1. **Extension tags.** `{% trans %}`, `{% do %}`, and `{% break %}` fail `Environment.parse` when the extension is not loaded, so those templates are skipped today. Add `[tool.types_for_jinja] extensions = [...]`, loaded into the parsing Environment. The stock extensions ship inside jinja2, so the dependency list is unchanged. Enabling i18n also injects `_`, `gettext`, and `ngettext` as known globals.
1. **Copier and Cookiecutter** need only what exists: configured delimiters, `template_dirs`, and declared globals. Confirm that with an integration test over a realistic layout of each.
