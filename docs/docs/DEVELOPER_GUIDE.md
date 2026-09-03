# Developer Notes

## Local Development

```sh
git clone https://github.com/kyleking/types-for-jinja.git
cd types-for-jinja
uv sync --all-extras

# See the available tasks
uv run calcipy
# Or use a local 'run' file (so that 'calcipy' can be extended)
./run

# Run the default task list (lint, auto-format, test coverage, etc.)
./run main

# Make code changes and run specific tasks as needed:
./run lint.fix test
```

### Maintenance

Dependency upgrades can be accomplished with:

```sh
uv lock --upgrade
uv sync --all-extras
```

## Publishing

Publishing is automated via GitHub Actions using PyPI Trusted Publishing. Tag creation triggers automated publishing.

```sh
./run release              # Bumps version, creates tag, pushes → triggers publish
./run release --suffix=rc  # For pre-releases
```

### Initial Setup

One-time setup to enable PyPI Trusted Publishing:

**Configure GitHub Environments**

Repository Settings → Environments:
- Create `testpypi` environment (no protection rules)
- Create `pypi` environment with "Required reviewers" enabled

**Register Trusted Publishers**

PyPI: https://pypi.org/manage/project/types_for_jinja/settings/publishing/
- Owner: `kyleking`
- Repository: `types-for-jinja`
- Workflow: `publish.yml`
- Environment: `pypi`
    - Or environment `testpypi` (for [TestPyPI](https://test.pypi.org/manage/account/publishing))

### Manual Publishing

For emergency manual publish:

```sh
export UV_PUBLISH_TOKEN=pypi-...
uv build
uv publish
```

## Current Status

<!-- {cts} COVERAGE -->
| File                                           | Statements | Missing | Excluded | Coverage |
|------------------------------------------------|-----------:|--------:|---------:|---------:|
| `types_for_jinja/__init__.py`                  | 4          | 0       | 0        | 100.0%   |
| `types_for_jinja/_runtime_type_check_setup.py` | 13         | 0       | 37       | 100.0%   |
| `types_for_jinja/cli.py`                       | 108        | 11      | 0        | 87.5%    |
| `types_for_jinja/complete.py`                  | 194        | 14      | 0        | 89.8%    |
| `types_for_jinja/components.py`                | 104        | 4       | 0        | 94.3%    |
| `types_for_jinja/config.py`                    | 72         | 0       | 0        | 100.0%   |
| `types_for_jinja/diagnostic.py`                | 11         | 0       | 0        | 100.0%   |
| `types_for_jinja/emit.py`                      | 39         | 0       | 0        | 100.0%   |
| `types_for_jinja/filters.py`                   | 19         | 0       | 0        | 100.0%   |
| `types_for_jinja/generate.py`                  | 130        | 0       | 0        | 100.0%   |
| `types_for_jinja/header.py`                    | 79         | 0       | 2        | 100.0%   |
| `types_for_jinja/layout.py`                    | 175        | 10      | 0        | 90.2%    |
| `types_for_jinja/lsp.py`                       | 210        | 29      | 0        | 81.2%    |
| `types_for_jinja/manifest.py`                  | 62         | 1       | 0        | 97.1%    |
| `types_for_jinja/members.py`                   | 154        | 14      | 0        | 88.0%    |
| `types_for_jinja/remap.py`                     | 248        | 17      | 0        | 89.0%    |
| `types_for_jinja/resolve.py`                   | 21         | 2       | 0        | 92.6%    |
| `types_for_jinja/suppress.py`                  | 26         | 0       | 0        | 100.0%   |
| `types_for_jinja/transpile.py`                 | 461        | 55      | 0        | 85.9%    |
| `types_for_jinja/wrapper.py`                   | 124        | 3       | 0        | 96.2%    |
| **Totals**                                     | 2254       | 160     | 39       | 90.3%    |

Generated on: 2026-09-02
<!-- {cte} -->
