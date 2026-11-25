# Enterprise integration and operating model

## Why this matters

Unreliable input affects downstream analytics, model features and retrieval quality. This gate makes quality requirements explicit, blocks out-of-contract staged data, and gives engineering and governance teams evidence to investigate changes.

### Deployment pattern

1. Land immutable input under a batch-specific object storage path. Record the source, batch ID, delivery time and upstream manifest.
2. Stage into a temporary file or isolated staging table; select the data contract version approved for the dataset.
3. Run the gate before publishing to a curated layer. Persist its aggregate JSON report and inspect the exit status.
4. Exit 0: continue to the warehouse or retrieval index. Exit 1: hold the batch and create a data-quality incident. Exit 2: treat the run as an infrastructure/configuration incident and investigate before retrying.
5. Publish the run status, contract hash and data owner in the catalog. Keep the SQLite file and reports in restricted storage, with retention and backups defined by policy.

For an orchestrator running a local staging file, use the CLI as a task:

```bash
python ai-readiness/ai_readiness.py "$STAGED_CSV" "$CONTRACT_JSON" \
  --history "$HISTORY_DB" --report "$RUN_REPORT"
```

Use a unique report filename per attempt. Schedule batch validation after source arrival rather than relying on a fixed clock alone. SQLite supports transactional access on a local disk; for distributed workers use a single history service or replace the SQLite store with a managed database. Do not share SQLite across network filesystems without validating their locking guarantees.

### Platform mappings

| Platform | Placement | Production adaptation |
| --- | --- | --- |
| Snowflake | Before publishing a staged batch to curated tables | Push row and key checks into SQL; write aggregate outcomes into an audit table. |
| Databricks | Between landing and curated Delta tables | Use Spark aggregations and distributed key checks; persist profiles in a governed table. |
| AWS Glue | Between S3 landing and target partitions | Validate via Glue/Spark for large datasets; propagate the gate status through the workflow. |
| dbt | Prior to downstream data marts | Express structural requirements as tests and publish run artifacts together with drift metrics. |
| RAG pipelines | Before indexing dataset-derived documents | Add document-specific checks, lineage, allowed sources and retrieval evaluations. |

The included Snowflake SQL is a standalone synthetic demo of structural checks, not a tested Snowflake deployment or complete port of the Python drift engine.

## Incident runbook

| Finding | Investigation | Resolution |
| --- | --- | --- |
| missing/unexpected column | Inspect the source schema and contract revision | Restore expected schema or approve a new version |
| missing/duplicate key | Check producer identifiers and replay behavior | Repair upstream data or controlled deduplication |
| freshness exceeded | Check ingestion lag and producer timestamp/timezone | Recover delayed data and rerun |
| categorical drift | Review source mix, customer behavior, new channel/product values | Determine whether the change is legitimate; update contract/baseline only after review |
| numeric drift | Compare fixed buckets and changes in source coverage | Confirm business event or fix incorrect transformations |
| row-count drift | Inspect manifests, late files, partial delivery and unexpected replays | Recover missing batches or reconcile duplicate delivery |

Assign data owners to set rules, operational engineers to triage failed runs, and governance owners to approve production baseline changes. Use least-privilege credentials for source reads and history writes.

## Measuring success

Measure gate rejection rate, repeated failure rate, time from detection to recovery, freshness SLA attainment, and downstream incidents attributable to data defects. Establish a pre-deployment baseline and compare like-for-like run periods. A decrease in incidents is evidence; it does not alone establish causation or financial ROI.

For a large warehouse, replace in-memory key sets with SQL or distributed aggregations; use the same fixed-bin definitions across batches so profile distances remain comparable. Validate sampling, thresholds and missed rare-category risks before using sampled profiles as a blocking control.
