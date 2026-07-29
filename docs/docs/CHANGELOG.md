## Unreleased

### Feat

- add stable rule codes (TJ###) and inline suppression
- **lsp**: check unsaved buffers live
- **transpile**: model macro bodies and cross-file extends/import context
- **wrapper**: enforce context types at runtime with beartype or pydantic
- **lsp**: add the language server with Neovim integration
- add the pre-commit hook and harden the transpiler
- declare Environment globals and add JSON/SARIF output
- add codegen-first checker spike

### Fix

- **check**: make the cache directory self-ignoring
- **transpile**: define the Jinja loop variable inside for bodies

### Refactor

- split out check_source, Diagnostic, and codes/suppress seams
