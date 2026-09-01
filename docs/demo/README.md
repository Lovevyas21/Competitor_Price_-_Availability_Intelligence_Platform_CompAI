# Demo & portfolio assets

Everything here is generated from, or measured against, the running system. No figure is
estimated; each is reproducible with the command beside it.

| File | What it is |
|---|---|
| [`dashboard.html`](dashboard.html) | Recruiter-facing one-page summary. Open directly, or view the published version. |
| [`architecture.md`](architecture.md) | Mermaid diagrams of what was **built**, plus a table of every deviation from the original plan and why |
| [`metrics.md`](metrics.md) | Measured results: scale, marts, forecast accuracy, performance, and stated limitations |
| [`sample-weekly-brief.md`](sample-weekly-brief.md) | Real generated brief, with its numeric-guard result in the header |
| [`dashboard-queries.sql`](dashboard-queries.sql) | 12 Metabase cards, each tested against the live database |
| [`portfolio.md`](portfolio.md) | Résumé bullets, LinkedIn post, 5-minute demo script, interview Q&A |

## Regenerating

```bash
make brief                      # rewrites sample-weekly-brief.md content
make test && make dbt-build     # the test counts quoted in metrics.md
make metabase                   # opt-in BI, then paste dashboard-queries.sql
```

## A note on the numbers

The figures are a snapshot taken 2026-09-01 with the stack idle and marts freshly built.
They move as ingestion runs. If you regenerate and see different values, that is the
system working, not the docs rotting — but re-read `metrics.md` before quoting anything
in an interview.

The limitations section of `metrics.md` is deliberately prominent. Naming what does not
yet work reads as judgement; discovering it mid-interview does not.
