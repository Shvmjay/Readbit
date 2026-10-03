# Deployment and Operations

> Readbit has **not** been deployed to a hosted environment from this repository. The API and web images were built and
> smoke-tested locally; this guide describes the intended production setup.

## Recommended infrastructure (cost-effective, no Kubernetes)

| Component | Recommendation | Notes |
|---|---|---|
| Web | Container (`infra/docker/web.Dockerfile`) on a managed container service (AWS App Runner / ECS Fargate, Google Cloud Run, Azure Container Apps, Fly.io, Render) | Needs `API_URL` pointing to the API's private URL |
| API | Container (`api.Dockerfile`, target `base`) on the same platform, ≥ 2 instances | Runs `alembic upgrade head` on start (see migrations) |
| Workers | Container (`api.Dockerfile`, target `worker`) — separate service, autoscaled on queue depth | Tesseract included for OCR |
| Scheduler | One `celery beat` instance | Hourly retention cleanup |
| Database | Managed PostgreSQL 16 with pgvector (RDS/Aurora, Cloud SQL, Azure Flexible Server, Neon, Supabase) | Automated backups + PITR |
| Queue | Managed Redis (ElastiCache, Memorystore, Upstash) | Used for Celery and rate limits |
| Storage | Private S3-compatible bucket (S3, GCS via S3 API, R2) | Block public access, SSE, lifecycle rules |
| Edge | Load balancer / CDN terminating TLS for the web origin | HSTS; only the web service is public |
| Malware scanning | ClamAV container (`clamav/clamav`) reachable only from the API | Signatures auto-update via freshclam |
| Monitoring | Centralized logs (JSON stdout), error tracking (`ERROR_TRACKING_DSN`, Sentry-compatible), uptime checks on `/health` and `/ready` | |

Only the web service needs to be public. Keep the API private (reachable from the web service) and set
`TRUST_PROXY_HEADERS=true`; otherwise leave it `false`.

## Environment and secrets

Use `.env.example` as the template. In production set at least:

```
APP_ENV=production
APP_URL=https://readbit.example            # public origin
CORS_ORIGINS=https://readbit.example
SECRET_KEY=<64 random hex chars>           # openssl rand -hex 32
DATABASE_URL=postgresql+psycopg://...
REDIS_URL=rediss://...
JOB_BACKEND=celery
STORAGE_PROVIDER=s3  STORAGE_BUCKET=...  STORAGE_REGION=...  (credentials via workload identity when possible)
DEFAULT_LLM_PROVIDER=anthropic  LLM_API_KEY=<secret>   (or keep extractive)
AI_DAILY_BUDGET=<USD>  USER_RATE_LIMIT=30  UPLOAD_RATE_LIMIT=10
EMAIL_DELIVERY=smtp  SMTP_HOST=...  SMTP_FROM="Readbit <no-reply@readbit.example>"  SMTP_USERNAME/SMTP_PASSWORD (secret)
MALWARE_SCANNER=clamav  CLAMAV_HOST=<clamd service>  CLAMAV_PORT=3310
```

Store secrets in the platform's secret manager; never bake them into images. Startup validation refuses production
with the dev secret, SQLite, local storage or non-Celery jobs.

## Deployment procedure

1. CI green on the commit (tests, evaluation gates, audits, container builds).
2. Build and push images tagged with the commit SHA:
   ```bash
   docker build -f infra/docker/api.Dockerfile --target base   -t REG/readbit-api:$SHA .
   docker build -f infra/docker/api.Dockerfile --target worker -t REG/readbit-worker:$SHA .
   docker build -f infra/docker/web.Dockerfile                 -t REG/readbit-web:$SHA .
   ```
3. **Migrate**: run `alembic upgrade head` once as a release task (the API command also runs it; with several
   instances prefer a dedicated one-off task and set the API command to `uvicorn ...` only). Migrations must be
   backwards-compatible with the previous release (expand → deploy → contract).
4. Deploy workers, then API, then web (rolling). Health checks: API `GET /health` (liveness) and `GET /ready`
   (database, storage, prompts); web `GET /`.
5. Smoke test: landing loads, `/api/v1/meta` via the web origin, guest start, upload a fixture, summary, lesson.

## Storage configuration

- Private bucket, "block public access" on, default encryption (SSE-S3 or KMS), versioning optional.
- Lifecycle rule as a backstop: delete objects under `books/` whose DB record no longer exists is handled by the
  retention job; add a rule expiring non-current versions after 7 days if versioning is enabled.
- CORS on the bucket is not needed (the browser never talks to storage).

## Workers

`celery -A app.workers.celery_app worker -Q documents,summaries,questions,maintenance,default --concurrency N`.
Tasks are idempotent with `acks_late`; `task_time_limit = MAX_PROCESSING_DURATION + 60`. Scale `documents` and
`questions` workers separately if needed (`-Q documents` on one pool, `-Q summaries,questions` on another).

## Domain and HTTPS

Point the domain at the load balancer/CDN; use managed certificates; redirect HTTP→HTTPS; HSTS is sent by the API in
production and should also be configured at the edge.

## Monitoring and alerting

- Logs: JSON lines with `request_id`, method, path, status, latency; job logs with job ids; AI executions in the DB.
- Alert on: `/ready` failing, 5xx rate, `processing_jobs` failed rate by `stage`/`error_code`, queue latency,
  `ai_executions.success=false` rate by `failure_category`, daily AI spend approaching `AI_DAILY_BUDGET`.
- Useful queries:
  ```sql
  SELECT date_trunc('day', created_at) d, sum(estimated_cost) FROM ai_executions GROUP BY 1 ORDER BY 1 DESC;
  SELECT stage, error_code, count(*) FROM processing_jobs WHERE status='failed' GROUP BY 1,2;
  SELECT task_type, avg(latency_ms), sum(estimated_cost) FROM ai_executions GROUP BY 1;
  ```

## Backups and restore

- Enable automated daily snapshots + point-in-time recovery (≥ 7 days) on PostgreSQL.
- Logical backup: `pg_dump -Fc "$DATABASE_URL" > readbit-$(date +%F).dump`; restore with
  `pg_restore --clean --if-exists -d "$DATABASE_URL" readbit-YYYY-MM-DD.dump`.
- Object storage: rely on provider durability; enable versioning if you need recovery from accidental deletes (note:
  user-initiated deletions must still be honoured — expire non-current versions).
- Test a restore into a staging database quarterly; run `alembic current` to confirm schema version.

## Rollback

- Application: redeploy the previous image tags (web, API, worker). Because migrations are expand/contract, the previous
  API works against the newer schema.
- Database: only if a migration is faulty — `alembic downgrade -1` (downgrades exist for every revision) or restore
  from PITR.
- AI incidents: set `DEFAULT_LLM_PROVIDER=extractive` to disable external model calls immediately.

## Cost controls

`AI_DAILY_BUDGET`, `USER_RATE_LIMIT`, `UPLOAD_RATE_LIMIT`, `MAX_UPLOAD_SIZE_MB`, `MAX_DOCUMENT_PAGES`,
`MAX_GENERATION_TOKENS`, per-task model selection, caching of summaries and question banks, and on-demand generation.
Monitor cost per book (`ai_executions` grouped by `book_id`).

## Operational checklist

- [ ] Secrets set in the secret manager; `SECRET_KEY` unique per environment
- [ ] `APP_ENV=production`; CORS and `APP_URL` set to the public origin
- [ ] API not publicly reachable (or `TRUST_PROXY_HEADERS=false`)
- [ ] Private bucket with encryption; DB encryption and backups/PITR enabled
- [ ] `alembic upgrade head` run; `/ready` green
- [ ] Workers and beat running; queue depth monitored
- [ ] Error tracking DSN configured (`pip install sentry-sdk`)
- [ ] AI budget and rate limits reviewed; live evaluation run passed if using a generative provider
- [ ] SMTP provider configured (domain SPF/DKIM verified) and a reset email received
- [ ] ClamAV (clamd) running with fresh signatures; `MALWARE_SCANNER=clamav`
- [ ] Restore test performed
