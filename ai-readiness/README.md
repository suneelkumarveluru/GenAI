# AI data readiness gate

Validate CSV data before ingestion into analytics, RAG or AI workflows. Uses Python 3.10+ standard library; no accounts or API keys required.

```sh
cd ai-readiness
python ai_readiness.py sample.csv contract.json
python -m unittest -v
```

The JSON contract supports required nonblank fields, unique nonblank keys, numeric bounds, minimum row counts, and optional freshness (`{"column":"updated_at","max_age_hours":24}`). Freshness timestamps must include a timezone. Reports contain rule counts rather than raw records. Exit codes: 0 pass, 1 quality failure, 2 input or configuration error.

Use the exit status to stop a pipeline before loading unreliable records. For example, run this against a staged CSV before a Snowflake or Databricks ingestion job. For very large data, uniqueness checks should run in the warehouse because the local checker stores unique keys in memory. Rule definitions should be reviewed by data owners; passing these structural checks does not establish factual correctness or privacy compliance.
