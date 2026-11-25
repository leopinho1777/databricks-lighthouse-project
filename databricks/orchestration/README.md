# orchestration

Databricks Asset Bundle that chains the pipeline end to end. It defines one job, **LH Nautical Orchestration**, that runs the `ingestion` job and then the `transformation` job (`dbt deps` + `dbt build`).

```
ingestion (run_job_task) ──> transformation (run_job_task)
```

* Each task retries up to 2 times; `max_concurrent_runs` is 1.
* Schedule: daily at **01:00 (America/Sao_Paulo)**, Quartz cron `0 0 1 * * ?`, status `UNPAUSED`.
* Definition: [`resources/orchestration_job.yml`](resources/orchestration_job.yml).

## Prerequisite

This bundle does not include the other two. It references the ingestion and transformation jobs by hardcoded `job_id`, so both must already be deployed in the target workspace, and the IDs in `orchestration_job.yml` must be updated to match.

## Deploy

```bash
databricks auth login
cd databricks/orchestration
databricks bundle deploy --target dev    # or prod
databricks bundle run ingestion_orchestration
```

Local overrides (workspace host, per-developer schema) go in `databricks.local.yml` at the repository root, which is not versioned.
