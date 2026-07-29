# Checker backends and batching

Parked design notes from 2026-07-29. Nothing here is implemented. Current work is on
transpilation, so this exists so the measurements do not have to be redone.

Measured with pyright 1.1.411 (mise pipx), ty 0.0.61, and mypy 2.3.0 on macOS.

## Why typed-jinja runs the checker itself

Worth settling first, because it rules out the "let users bring their own checker and we
just publish hooks" design.

The stub is generated Python under `.typed_jinja_cache/`, and every checker reports
positions in that file. Compare what typed-jinja prints:

```
templates/page.jinja:5:14 error: Cannot access attribute "nmae" for class "User" (TJ002)
```

against what `ty check` prints over the same cache directory:

```
.typed_jinja_cache/templates_page_jinja.py:7:9: error[unresolved-attribute] Object of type `User` has no attribute `nmae`
```

`_template_line` in `typed_jinja/check.py` walks the `# L<n>` markers backwards to turn the
first into the second. Whoever owns the subprocess owns the remap. Hand the invocation to
the end user and they get diagnostics pointing at synthetic Python they never wrote.

A post-processor (`ty check --output-format concise | typed-jinja remap`) would work, but it
still requires parsing each checker's stdout, which is the same work as owning the
subprocess, with worse ergonomics and no control over the exit code. Not worth it.

One real point survives from that direction: `_write_pyright_config` writes a fresh
`pyrightconfig.json` and ignores whatever the project already configured, so the stub is
checked under different settings than the project's own source. That matters most for a
project using the mypy pydantic plugin, or custom stub paths. Backend discovery answers
"which binary" and does not answer "under whose config". Decide separately.

## All three backends agree

Checked against a real generated stub (dataclass context, bad attribute, undefined name,
loop variable, filter call, bad method on `int`). pyright, ty, and mypy each reported the
same four errors on the same template lines. The abstraction is sound.

## What varies between backends

| | ty | pyright | mypy |
|---|---|---|---|
| import path | `--extra-search-path DIR` | `extraPaths` in `pyrightconfig.json` | `MYPYPATH` env |
| machine output | `--output-format gitlab` (JSON) or `concise` (regex) | `--outputjson` | `--output json` |
| line base | 1 | 0 | 1 |
| column base | 1 | 0 | 0 |
| undefined name | `unresolved-reference` | `reportUndefinedVariable` | `name-defined` |
| bad attribute | `unresolved-attribute` | `reportAttributeAccessIssue` | `attr-defined` |
| bad index | `invalid-argument-type` | `reportArgumentType` / `reportCallIssue` | `index` / `call-overload` |

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

A registry in priority order plus `resolve_backend(config)` walking it for the first
`shutil.which` hit.

## TJ codes are not portable across backends

The thing that actually breaks. Codes are a user-facing contract because suppression
comments name them, so `{# type: ignore[TJ003] #}` written on a machine running mypy
suppresses nothing on a machine running ty, which files the same error under
`invalid-argument-type` and would map to TJ005. Silent discovery makes suppressions
machine-dependent.

Related: `RULE_CODES` maps TJ003 to `reportIndexIssue`, and pyright never emitted it in
testing for dict or list key-type errors. Those came out as `reportArgumentType` and
`reportCallIssue`, so TJ003 may already be unreachable.

Preferred fix is narrowing the catalog to categories every backend agrees on (undefined
name, bad attribute, bad call, everything else) rather than keeping codes only one backend
can produce.

## Batching is the large performance win

`cli.py:37` loops `check_file(template)` per template, and `_run_pyright` launches one
subprocess per call, so checking N templates pays N process startups. Startup dominates
everything else.

25 generated stubs, `time` on a warm cache:

| | 25 separate invocations | 1 batched invocation | speedup |
|---|---|---|---|
| ty | 1.22s | 0.037s | 33x |
| pyright | 12.02s | 0.498s | 24x |

Batched runs found the same 25 diagnostics as the separate runs, so this is not an
artifact of skipped work. Per-invocation floor is roughly 480ms for pyright and 49ms for
ty, paid regardless of how small the template is. That floor is why the pre-commit hook and
the LSP feel slow.

ty batched is about 13x faster than pyright batched (0.037s against 0.498s).

Ideas, in rough order of value:

- Write every stub to the cache directory first, run the checker once over the directory,
  then demultiplex diagnostics back to templates. `pyrightconfig.json` already sets
  `include: ['.']`, so pyright needs only the explicit filename argument dropped
- Keep an explicit stub-to-template manifest rather than reversing `_safe_name`, since that
  regex is lossy
- Delete orphaned stubs before a batch run. In per-file mode a stale stub from a deleted or
  renamed template is invisible, and in batch mode it produces phantom errors
- Add `check_files(paths)` alongside `check_file`. The LSP live-buffer path through
  `check_source` stays single-file
- Content-hash manifest to skip re-transpiling and re-checking unchanged templates. The hash
  has to include the resolved base and imported template contents, because `extends` and
  `import` are inlined at transpile time, so a child stub changes when its parent does
- For the LSP, replace per-keystroke subprocess launches with a persistent language server
  and proxy its diagnostics. `ty server` exists. Larger architecture change, probably v2
- Do not add process-level parallelism on top of batching. ty ran at 130% CPU and pyright at
  151% during the batched runs, so both already parallelize internally

## Cost to know before starting

Seven test files gate on `shutil.which('pyright')`, several assert on literal pyright rule
names (`tests/test_v11_crossfile.py:34`, `tests/test_v11_macro.py:43`,
`tests/test_v1_realworld.py:35`), and `report.py` emits a `pyrightRule` SARIF property.
Switching the default means rewriting those against neutral TJ codes.

## Open questions

- Make `ty` a hard dependency? It is a zero-dependency wheel on PyPI, so it guarantees every
  install has a working backend and removes the `PyrightNotFoundError` path entirely.
  Against it: ty is pre-1.0, and its diagnostics still move between releases
- If discovery stays, default order ty then pyright then mypy, with
  `[tool.typed_jinja] checker` to pin. The resolved backend should appear in the summary
  line so a CI failure that does not reproduce locally is diagnosable
- Whether to read the project's existing checker config instead of writing our own
- `pyright[nodejs]` on PyPI bundles node through `nodejs-wheel-binaries`, and `basedpyright`
  requires it unconditionally. Either removes the "pyright must be on PATH" problem without
  changing the inference engine, if staying on pyright turns out to matter

## Reproducing the benchmark

25 stubs shaped like transpiler output, each with one deliberate bad attribute, then
compare a shell loop over the files against a single invocation on the directory. Confirm
both report the same diagnostic count before trusting the timings.
