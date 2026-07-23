# admrules

Administrative rules pipeline package for `target=admrul`.

Scope:

- `api_client.py`: `admrul` and `admrulOldAndNew` API wrappers.
- `cache.py`: raw history detail XML cache under `.cache/admrule/`.
- `checkpoint.py`: resumable page/detail checkpoint.
- `fetch_cache.py`: `history=True` / `nw=2` history list and detail cache fetch loop.
- `converter.py`: raw XML to Markdown/frontmatter.
- `render_spec.md`: path and frontmatter rendering contract mirrored by the Rust compiler.
- `byls_metadata.py`: attachment metadata helpers.
- `validate.py`: frontmatter and binary-free invariant checks.

Full unfiltered `fetch_cache.py` runs prune `.cache/admrule/*.xml` files that are
not present in the latest `history=True` / `nw=2` search result, so compiler
input stays reproducible from a fresh history cache.

`import_admrules.py` writes revisions in `발령일자`, `행정규칙일련번호`, path order.
The rule identity is `행정규칙ID`, falling back to `행정규칙일련번호` only when
the ID is missing. Revisions that contain `폐지` delete the latest file for that
identity from `HEAD`; earlier text remains available in Git history.

## Known upstream gaps

Some serials appear in the `nw=2` search index but their detail lookup fails
permanently: the API answers `필수 입력값이 존재하지 않습니다` no matter how often
it is retried, which points at a defect on the 법령정보센터 side rather than a
transient error. As of 2026-06-16 this affected 124 of 138,590 serials (0.09%).
Those serials are never cached and are therefore excluded from compiler input.

`detail_failure_allowlist.py` + `data/known_detail_failures.yaml` are the
mechanism for accepting such failures deliberately; each entry carries an
`expires_on` so an accepted gap is re-checked instead of being forgotten.
