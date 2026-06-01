## What this PR does

<!-- One paragraph summary. -->

## Related stage / TODO item

<!-- Stage N from docs/IMPLEMENTATION_PLAN.md or a TODO.md checkbox. -->

## Checklist

- [ ] Does not filter files during ingest (classification = stats only)
- [ ] Does not delete from the source card
- [ ] Does not write to `imports/` (immutable source of truth)
- [ ] Subprocess calls use argument lists, not `shell=True`
- [ ] New copy/move paths have a `--dry-run` test
- [ ] Exit codes match DATA_MODEL.md
- [ ] Logs and metrics are emitted for the new path
- [ ] Acceptance tests from IMPLEMENTATION_PLAN pass (or are added here)
