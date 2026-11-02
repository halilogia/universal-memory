# Context packs

`context_injector.build_context()` and the MCP `memory_context` tool produce a
character-bounded pack of valid canonical conventions, decisions, and lessons.

- `project="all"` or `project="*"` considers every project, including global
  records. With an empty query, all eligible cards compete by type and recency.
- For a named project, `include_global=True` (default) adds global records and
  cards from other projects matching at least one non-stopword query token.
  An empty query does not pull in foreign project cards.
- `include_global=False` restricts a named project to its own records. Explicit
  `all`/`*` selection takes precedence over this flag.
- Only a named project's latest eligible handoff contributes open tasks.
  All-project packs omit handoffs to avoid mixing unrelated task lists.
- Existing canonical status, agent scope, and bitemporal validity filters apply
  across projects. Python callers may opt into proposals as before.

Ranking rewards query coverage and capped term frequency, with title occurrences
weighted three times body occurrences. Recency uses a gently decaying chronological
rank; relevant negative lessons receive an additional boost. Returned `cards`
are score-ordered and include `project`; the rendered text groups them by kind.

The whole-word triggers `doğrulama`, `verification`, `review`, `kural`, and `test`
(case insensitive, Turkish-folded) append the Evidence Checklist automatically.
`inject_verification_template=True` forces it for other queries. `False` leaves
automatic detection enabled. The checklist requests concrete test, build, viewport,
and console evidence; it does not claim those checks ran.

The complete checklist is reserved before selecting cards. A smaller `max_chars`
raises `ValueError` (reported as an MCP tool error), rather than truncating the
checklist. Without the checklist, zero is a valid empty-text budget. Cards that
cannot fit completely are omitted. `card_chars` must be positive.

```bash
python context_injector.py --project all --query "sqlite connections" --json
python context_injector.py --project Demo --no-global --query "logging"
python context_injector.py --project Demo --inject-verification-template
python -m pytest -q
```
