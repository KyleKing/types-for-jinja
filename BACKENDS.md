# Checker backends and batching

Design notes from 2026-07-29, revised 2026-08-04 once `generate` was made to check clean under all three backends. Backend discovery for `check` and the batching work below are still unimplemented. This exists so the measurements do not have to be redone.

Measured with pyright 1.1.411 (mise pipx), ty 0.0.61, and mypy 2.3.0 on macOS.

Superseded in part on 2026-08-04: PLAN.md's "Direction (2026-08)" removes `check` entirely, so everything below about `check` owning a subprocess describes the system being retired. The measurements, the backend table, and the suppression findings still hold and are what the pivot rests on.

## Decision: `generate` is the portable path, `check` stays on pyright

`types-for-jinja generate` writes stubs that pyright, ty, and mypy all read the same way, verified by `tests/test_backends.py` on every run where the backend is installed. `check` keeps its own pyright subprocess and its `TJ###` codes, because it owns the diagnostics it prints.

Two defects had to be fixed before that was true, and both were invisible under pyright alone:

- the stub reused one `_` name for every expression check, so mypy took its declared type from the first assignment and reported `Incompatible types in assignment` on every later one. The preamble now declares `_: _TJAny`
- the generated filter signatures had `...` bodies in a real module, which ty reports as `empty-body`. They now raise

Over the example templates that took ty from 58 diagnostics to the 3 that `greeting_bad.html.jinja` is supposed to have, and mypy from 12 to the same 3.

## Why types-for-jinja runs the checker itself

This settles whether "let users bring their own checker" is possible. It is, for most templates, and `types-for-jinja generate` is that path. `types-for-jinja check` still owns a subprocess and everything below still applies to it.

The stub is generated Python under `.types_for_jinja_cache/`, and every checker reports positions in that file. Compare what types-for-jinja prints:

```
templates/page.jinja:5:14 error: Cannot access attribute "nmae" for class "User" (TJ002)
```

against what `ty check` prints over the same cache directory:

```
.types_for_jinja_cache/templates_page_jinja.py:7:9: error[unresolved-attribute] Object of type `User` has no attribute `nmae`
```

`_template_line` in `types_for_jinja/check.py` walks the `# L<n>` markers backwards to turn the first into the second. Whoever owns the subprocess owns the remap.

The way out is to make the remap unnecessary rather than to relocate it. If generated line N is template line N, any checker reports the right line with nothing in between. See the next section for how far that gets.

A post-processor (`ty check --output-format concise | types-for-jinja remap`) remains the answer for the templates with no aligned form, and for recovering columns. It parses each checker's stdout, which is the work owning the subprocess already does, so it is worth adding only if those cases start to matter.

One real point survives regardless: `_write_pyright_config` writes a fresh `pyrightconfig.json` and ignores whatever the project already configured, so the stub is checked under different settings than the project's own source. That matters most for a project using the mypy pydantic plugin, or custom stub paths. Backend discovery answers "which binary" and does not answer "under whose config". Decide separately.

## Line-aligned codegen removes the backend problem for most templates

Measured over 126 templates, 11 from `examples/` and 115 real ones from mkdocs-material.

|                                                | count | share |
| ---------------------------------------------- | ----- | ----- |
| exact line-aligned stub                        | 120   | 95.2% |
| no aligned form, keeps `# L` markers           | 3     | 2.4%  |
| `UnsupportedTemplateError` escapes `transpile` | 3     | 2.4%  |

Both remainders have since been addressed. The 3 unaligned templates were all `{% if %}...{% else %}...{% endif %}` on one physical line, which now collapses to `_ = (a if cond else b)`, because a conditional expression narrows the same way the branches did and fits where two compound statements could not. `UnsupportedTemplateError` is public and caught by both `generate` and `check`, so one template using a construct the transpiler does not model is skipped with a reason (`TJ012`) rather than ending the run. `{% set ns.count = 1 %}` is the common case, since `namespace` is a real Jinja idiom the transpiler has no model for.

Against the example templates carrying a real `{#def #}` header, the aligned stubs checked by raw pyright produce diagnostics identical to `check_file`. `tests/test_layout.py` asserts that parity, along with every generated file parsing as Python and the sidecar binding the declared context.

Both checkers find the same three errors on the same lines in a generated stub, with no types-for-jinja process running:

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

- the file path and the column. Your checker prints `_jinja_stubs/templates/profile_html.py:5:10`, where the template has `{{ user.naem }}` at `templates/profile.jinja:5:18`. The line is right and the stub path mirrors the template tree, so the mapping is readable, but nothing makes the checker name the template. Go's `//line` directives are why templ can and Python has no equivalent for type checkers. The editor path does not have this problem: the LSP reports template positions with columns
- `loop` is bound at module level, so using `loop` outside a `{% for %}` is not flagged

The output directory must not start with a dot. Pyright excludes `**/.*` by default and reports a clean run over zero files, which is why the default is `_jinja_stubs` and not `.types_for_jinja`. Stub paths mirror the template tree with only the filename mangled, because a module name cannot carry the template's extension.

## All three backends agree

Checked against a real generated stub (dataclass context, bad attribute, undefined name, loop variable, filter call, bad method on `int`). pyright, ty, and mypy each reported the same four errors on the same template lines. The abstraction is sound.

`tests/test_backends.py` holds that: it runs whichever backends are installed over the same generated tree and asserts each agrees with `check_file`, and that ty and mypy agree with each other. CI sets `TYPES_FOR_JINJA_REQUIRE_CHECKERS` so a missing backend fails rather than skips.

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

`generate` sidesteps the code question. Users see their own checker's native codes, so there is nothing to map.

Suppression is solved, by dropping the codes rather than translating them. Measured behaviour of a bare ignore comment:

|                          | pyright    | ty         | mypy       |
| ------------------------ | ---------- | ---------- | ---------- |
| `# type: ignore`         | suppresses | suppresses | suppresses |
| `# ty: ignore`           | no         | suppresses | no         |
| `# pyright: ignore`      | suppresses | no         | no         |
| `# type: ignore[<code>]` | suppresses | no         | suppresses |

So `{# type: ignore #}` and `{# type: ignore[TJ002] #}` both emit one blanket ignore on the aligned line, spelled per `[tool.types_for_jinja] suppression`: `portable` (the default, `# type: ignore`), or `mypy`, `pyright`, `ty`. An unknown value is rejected at config load, because a silent fallback would emit comments the project's checker does not honour.

Two things ruled out the obvious alternatives. Stacking `# type: ignore  # ty: ignore` works, but ty then reports `unused-ignore-comment` on the second one, because the first already suppressed it. And per-code brackets need a TJ-to-native table that is one-to-many (TJ004 is ty's `invalid-argument-type` or `too-many-positional-arguments` depending on the call), where a wrong guess both fails to suppress and adds an `ignore-comment-unknown-rule` warning.

On the unaligned fallback the ignore goes in front of the `# L<n>` marker, since `_template_line` reads the marker off the end of the line and a checker only honours the directive when it opens the comment.

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
- If discovery stays, default order ty then pyright then mypy, with `[tool.types_for_jinja] checker` to pin. The resolved backend should appear in the summary line so a CI failure that does not reproduce locally is diagnosable
- Whether to read the project's existing checker config instead of writing our own
- Staleness for `generate`. `--check` gates it, but committing the stubs is what makes a fresh clone typecheck correctly before anyone runs types-for-jinja
- A `types-for-jinja remap` filter (`ty check --output-format concise | types-for-jinja remap`) to rewrite stub paths and columns back to templates in CI output. It is the only way to recover what `//line` gives Go, and it parses each backend's stdout, which is the work backend discovery would need anyway
- `namespace` has no model in the transpiler, so `{% set ns.count = 1 %}` skips the whole template. Binding `ns` from `namespace(...)` would need the call itself typed, or every such template reports `namespace` undefined, which is worse than skipping
- `pyright[nodejs]` on PyPI bundles node through `nodejs-wheel-binaries`, and `basedpyright` requires it unconditionally. Either removes the "pyright must be on PATH" problem without changing the inference engine, if staying on pyright turns out to matter

## Reproducing the benchmark

25 stubs shaped like transpiler output, each with one deliberate bad attribute, then compare a shell loop over the files against a single invocation on the directory. Confirm both report the same diagnostic count before trusting the timings.
