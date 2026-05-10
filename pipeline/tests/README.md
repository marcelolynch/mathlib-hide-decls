# `pipeline/tests/`

Unit tests for the parsers that have historically generated the most
defects: the centralized attribute scanner and the build-log error
classifier.

## Running

From the repo root:

```bash
pytest pipeline/tests/
```

For verbose output or a single test:

```bash
pytest pipeline/tests/ -v
pytest pipeline/tests/test_policy_attrs.py::test_same_line_single -v
```

The tests have no external dependencies beyond `pytest`. They do not
load the census or touch a mathlib checkout.

## What's covered

### `test_policy_attrs.py`

`policy.parse_attrs(src_lines, def_line_idx, kind_keyword)` returns
every attribute token applying to the `def` / `lemma` / `theorem` /
`abbrev` at `src_lines[def_line_idx]`. The function scans two
regions:

1. The same line, prefix before the `kind` keyword
   (`@[simp, norm_cast] lemma X`).
2. Preceding contiguous lines that are `@[…]` blocks, doc comments,
   or blank. Stops at the first unrelated line.

The 16 cases cover:

- same-line single, same-line multiple attributes
- preceding-line single, multiple
- doc-comment passthrough
- multi-token attributes with parens (`@[deprecated foo (since := "v3.0")]`)
- modifier interleaving (`noncomputable`, `protected`, `partial`)
- already-private decls
- blank lines between attribute and decl
- stop at previous decl
- `abbrev` keyword

### `test_revert_parser.py`

The error-line classifier in `bulk_revert.parse_errors`. The 12 cases
cover every recognized pattern:

- `Cannot add attribute […]: Declaration \`X\` must be public`
- `Unknown identifier \`X\`` (backticks — Lean does not use single quotes)
- `Unknown constant \`X\``
- `A private declaration \`X\` exists`
- `Invalid field \`f\`: …`
- `(kernel) declaration has metavariables 'X'`
- `compiler IR check failed at \`X\``
- `Failed to rewrite using equation theorems for \`X\``
- `failed to synthesize <Class>`
- `unknown projection \`X\``
- `.formatter` / `.parenthesizer` / `.delaborator` suffix stripping
- Module-wide trigger for unrecognized cascading errors

## CI

Tests run on every PR via `.github/workflows/tests.yml`.
