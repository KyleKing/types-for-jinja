# Checker backends and batching

Parked design notes from 2026-07-29. The backend and batching work below is unimplemented; `typed_jinja/layout.py` and `typed_jinja/generate.py` are the part that shipped. This exists so the measurements do not have to be redone.

Measured with pyright 1.1.411 (mise pipx), ty 0.0.61, and mypy 2.3.0 on macOS.

## Why typed-jinja runs the checker itself

This settles whether "let users bring their own checker" is possible. It is, for most templates, and `typed-jinja generate` is that path. `typed-jinja check` still owns a subprocess and everything below still applies to it.

The stub is generated Python under `.typed_jinja_cache/`, and every checker reports positions in that file. Compare what typed-jinja prints:

```
templates/page.jinja:5:14 error: Cannot access attribute "nmae" for class "User" (TJ002)
```

against what `ty check` prints over the same cache directory:

```
.typed_jinja_cache/templates_page_jinja.py:7:9: error[unresolved-attribute] Object of type `User` has no attribute `nmae`
```

`_template_line` in `typed_jinja/check.py` walks the `# L<n>` markers backwards to turn the first into the second. Whoever owns the subprocess owns the remap.

The way out is to make the remap unnecessary rather than to relocate it. If generated line N is template line N, any checker reports the right line with nothing in between. See the next section for how far that gets.

A post-processor (`ty check --output-format concise | typed-jinja remap`) remains the answer for the templates with no aligned form, and for recovering columns. It parses each checker's stdout, which is the work owning the subprocess already does, so it is worth adding only if those cases start to matter.

One real point survives regardless: `_write_pyright_config` writes a fresh `pyrightconfig.json` and ignores whatever the project already configured, so the stub is checked under different settings than the project's own source. That matters most for a project using the mypy pydantic plugin, or custom stub paths. Backend discovery answers "which binary" and does not answer "under whose config". Decide separately.

## Line-aligned codegen removes the backend problem for most templates

Measured over 126 templates, 11 from `examples/` and 115 real ones from mkdocs-material.

|                                           | count | share |
| ----------------------------------------- | ----- | ----- |
| exact line-aligned stub                   | 120   | 95.2% |
| no aligned form, keeps `# L` markers      | 3     | 2.4%  |
| `_UnsupportedError` escapes `transpile()` | 3     | 2.4%  |

Against the 9 example templates carrying a real `{#def #}` header, the aligned stubs checked by raw pyright produce diagnostics identical to `check_file`, 9 of 9.

Both checkers find the same three errors on the same lines in a generated stub, with no typed-jinja process running:

```
_jinja_stubs/templates/profile_html.py:5:10  - error: Cannot access attribute "naem" for class "User"
_jinja_stubs/templates/profile_html.py:5:  error: "User" has no attribute "naem"  [attr-defined]
```

Five transformations get this from 30% to 95%, each traced to a measured failure:

- hoist `loop` to the preamble so a for-body's first line is free for real statements
- drop the `_render` placeholder `pass`, which carries the header's line number and sorts behind any macro defined above it. This alone was 73 of the original 78 fallbacks
- route cross-file macro stubs to a sidecar module, since they carry another template's line numbers
- demote `{% if x %}{% endif %}` to `_ = x`, a simple statement that can share a physical line where a second compound statement cannot
- relocate `else:`, because Jinja records no line number for `{% else %}`

The preamble collapses onto the header's own line as `;`-joined simple statements, so alignment holds no matter how many imports and globals a project declares. Emitting at module level rather than inside `_render` frees the indent level the template's top level needs, which means every declared name must be bound (`user: User = _tj_any`) and not just annotated, or the real errors disappear under `"user" is unbound`.

What it does not do:

- columns, only lines. Pyright reports column 10 where the template has `{{ user.naem }}` at column 18
- `{% else %}` sharing a physical line with its branch has no aligned form, which is all 3 fallbacks
- `loop` is bound at module level, so using `loop` outside a `{% for %}` is not flagged

The output directory must not start with a dot. Pyright excludes `**/.*` by default and reports a clean run over zero files, which is why the default is `_jinja_stubs` and not `.typed_jinja`. Stub paths mirror the template tree with only the filename mangled, because a module name cannot carry the template's extension.

## All three backends agree

Checked against a real generated stub (dataclass context, bad attribute, undefined name, loop variable, filter call, bad method on `int`). pyright, ty, and mypy each reported the same four errors on the same template lines. The abstraction is sound.

## What varies between backends

|                | ty                                                   | pyright                                  | mypy                      |
| -------------- | ---------------------------------------------------- | ---------------------------------------- | ------------------------- |
| import path    | `--extra-search-path DIR`                            | `extraPaths` in `pyrightconfig.json`     | `MYPYPATH` env            |
| machine output | `--output-format gitlab` (JSON) or `concise` (regex) | `--outputjson`                           | `--output json`           |
| line base      | 1                                                    | 0                                        | 1                         |
| column base    | 1                                                    | 0                                        | 0                         |
| undefined name | `unresolved-reference`                               | `reportUndefinedVariable`                | `name-defined`            |
| bad attribute  | `unresolved-attribute`                               | `reportAttributeAccessIssue`             | `attr-defined`            |
| bad index      | `invalid-argument-type`                              | `reportArgumentType` / `reportCallIssue` | `index` / `call-overload` |

That table is the interface spec. A frozen dataclass per backend covers it:

```python
@dataclass(frozen=True)
class Backend:
    name: str
    executable: str
    argv: Callable[[Path], list[str]]
    prepare: Callable[[Path, Path], Mapping[str, str]]  # write config, return env overrides
    parse: Callable[[str], list[Diagnostic]]
    rule_codes: Mapping[str, str]
```

A registry in priority order plus `resolve_backend(config)` walking it for the first `shutil.which` hit.

## TJ codes are not portable across backends

The thing that actually breaks. Codes are a user-facing contract because suppression comments name them, so `{# type: ignore[TJ003] #}` written on a machine running mypy suppresses nothing on a machine running ty, which files the same error under `invalid-argument-type` and would map to TJ005. Silent discovery makes suppressions machine-dependent.

Related: `RULE_CODES` maps TJ003 to `reportIndexIssue`, and pyright never emitted it in testing for dict or list key-type errors. Those came out as `reportArgumentType` and `reportCallIssue`, so TJ003 may already be unreachable.

Preferred fix is narrowing the catalog to categories every backend agrees on (undefined name, bad attribute, bad call, everything else) rather than keeping codes only one backend can produce.

`generate` sidesteps the code question and inherits the suppression one. Users see their own checker's native codes, so there is nothing to map. But `{# type: ignore[TJ003] #}` has to become a real `# type: ignore[...]` on the aligned line, and the code inside those brackets is backend-specific. Unsolved.

## Batching is the large performance win

This applies to `check` only. `generate` writes files and exits, so the user's own checker pays a single startup and keeps its own incremental cache.

`cli.py:37` loops `check_file(template)` per template, and `_run_pyright` launches one subprocess per call, so checking N templates pays N process startups. Startup dominates everything else.

25 generated stubs, `time` on a warm cache:

|         | 25 separate invocations | 1 batched invocation | speedup |
| ------- | ----------------------- | -------------------- | ------- |
| ty      | 1.22s                   | 0.037s               | 33x     |
| pyright | 12.02s                  | 0.498s               | 24x     |

Batched runs found the same 25 diagnostics as the separate runs, so this is not an artifact of skipped work. Per-invocation floor is roughly 480ms for pyright and 49ms for ty, paid regardless of how small the template is. That floor is why the pre-commit hook and the LSP feel slow.

ty batched is about 13x faster than pyright batched (0.037s against 0.498s).

Ideas, in rough order of value:

- Write every stub to the cache directory first, run the checker once over the directory, then demultiplex diagnostics back to templates. `pyrightconfig.json` already sets `include: ['.']`, so pyright needs only the explicit filename argument dropped
- Keep an explicit stub-to-template manifest rather than reversing `_safe_name`, since that regex is lossy
- Delete orphaned stubs before a batch run. In per-file mode a stale stub from a deleted or renamed template is invisible, and in batch mode it produces phantom errors
- Add `check_files(paths)` alongside `check_file`. The LSP live-buffer path through `check_source` stays single-file
- Content-hash manifest to skip re-transpiling and re-checking unchanged templates. The hash has to include the resolved base and imported template contents, because `extends` and `import` are inlined at transpile time, so a child stub changes when its parent does
- For the LSP, replace per-keystroke subprocess launches with a persistent language server and proxy its diagnostics. `ty server` exists. Larger architecture change, probably v2
- Do not add process-level parallelism on top of batching. ty ran at 130% CPU and pyright at 151% during the batched runs, so both already parallelize internally

## Cost to know before starting

Seven test files gate on `shutil.which('pyright')`, several assert on literal pyright rule names (`tests/test_v11_crossfile.py:34`, `tests/test_v11_macro.py:43`, `tests/test_v1_realworld.py:35`), and `report.py` emits a `pyrightRule` SARIF property. Switching the default means rewriting those against neutral TJ codes.

## Open questions

- Make `ty` a hard dependency? It is a zero-dependency wheel on PyPI, so it guarantees every install has a working backend and removes the `PyrightNotFoundError` path entirely. Against it: ty is pre-1.0, and its diagnostics still move between releases
- If discovery stays, default order ty then pyright then mypy, with `[tool.typed_jinja] checker` to pin. The resolved backend should appear in the summary line so a CI failure that does not reproduce locally is diagnosable
- Whether to read the project's existing checker config instead of writing our own
- Whether `generate` becomes the default and `check` becomes the fallback for the aligned minority, which would drop the runtime dependency set to jinja2 alone
- Staleness for `generate`. `--check` gates it, but committing the stubs is what makes a fresh clone typecheck correctly before anyone runs typed-jinja
- Three templates crash `transpile()` with `_UnsupportedError` escaping to the caller (`_emit_for` calls `_target` uncaught, among others), which takes down a whole run rather than skipping one template
- `pyright[nodejs]` on PyPI bundles node through `nodejs-wheel-binaries`, and `basedpyright` requires it unconditionally. Either removes the "pyright must be on PATH" problem without changing the inference engine, if staying on pyright turns out to matter

## Reproducing the benchmark

25 stubs shaped like transpiler output, each with one deliberate bad attribute, then compare a shell loop over the files against a single invocation on the directory. Confirm both report the same diagnostic count before trusting the timings.
