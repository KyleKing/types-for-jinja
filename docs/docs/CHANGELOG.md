## Unreleased

### Fix

- **generate**: skip a template whose header cannot be read

## 1.1.2 (2026-08-15)

### Fix

- **header**: accept a defaulted declaration before an undefaulted one

## 1.1.1 (2026-08-12)

### Fix

- **wrapper**: emit a valid signature for a header with no parameters
- **cli**: count the manifest in the wrapper write total
- **wrapper**: prune the wrappers whose templates are gone
- convert Path to PurePosixPath via as_posix on Windows (#1)

## 1.1.0 (2026-08-05)

### Feat

- **transpile**: check a typed {% include %} as a parameterized call

## 1.0.0 (2026-08-04)

### Feat

- **emit**: mangle templated directory names so Copier and Cookiecutter check
- **cli**: broaden template discovery and default to template_dirs
- **transpile**: check templates that use namespace() and Jinja's globals
- **config**: declare jinja2 extensions so their tags parse
- **components**: check JinjaX component tags against their own header
- **header**: read JinjaX's one-line form, defaults, and untyped names
- **lsp**: resolve members through any Python language server
- **nvim**: mirror stub diagnostics onto the template buffer
- **lsp**: write stubs instead of running a checker
- **cli**: add remap to name templates in checker output
- **generate**: record each stub's template in a manifest
- **generate**: make the stubs check clean under ty, mypy, and pyright
- **lsp**: complete attributes by asking pyright what the type offers
- **lsp**: complete Jinja's own filters, tests, and tags
- support custom Jinja delimiters and package-relative template dirs
- give Jinja's built-in filters and tests real return types
- follow {% include %} context and whole {% extends %} chains
- type macro parameters from a macro's own {#def #} block
- **cli**: add `types-for-jinja wrapper` for typed render call sites
- **lsp**: complete and describe the names a template's typed context provides
- **generate**: write stubs for an existing type checker to pick up
- **layout**: align generated stubs to their template line numbers
- add stable rule codes (TJ###) and inline suppression
- **lsp**: check unsaved buffers live
- **transpile**: model macro bodies and cross-file extends/import context
- **wrapper**: enforce context types at runtime with beartype or pydantic
- **lsp**: add the language server with Neovim integration
- add the pre-commit hook and harden the transpiler
- declare Environment globals and add JSON/SARIF output
- add codegen-first checker spike

### Fix

- **generate**: make stub-to-stub imports resolve without a search path
- **lsp**: prepare the checker cache on first use, not on import
- restore the collapsed {#def #} headers and stop them silently breaking
- **deps**: bump gitpython to 3.1.57
- **tests**: satisfy mypy on the test suite
- **transpile**: rename Jinja variables that collide with Python keywords
- **check**: make the cache directory self-ignoring
- **transpile**: define the Jinja loop variable inside for bodies

### Refactor

- remove the check subcommand and its pyright subprocess
- **transpile**: expose emitted lines and flag cross-file definitions
- split out check_source, Diagnostic, and codes/suppress seams


- rename to types-for-jinja
