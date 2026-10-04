# Infra-Guard Monitoring

Minimal Prometheus + Grafana stack that scrapes the metrics written by the cleanup script.

- `docker-compose.yml` — Prometheus, node-exporter (textfile collector), Grafana
- `prometheus.yml` — scrape configuration
- `grafana/provisioning/` — auto-provisioned Prometheus datasource and Infra-Guard Overview dashboard

## Run

```bash
docker compose up -d
```

- Prometheus: http://localhost:9090
- node-exporter: http://localhost:9100 (exposes the textfile metrics)
- Grafana: http://localhost:3000 (defaults to `admin`/`admin`, override with `GRAFANA_USER`/`GRAFANA_PASSWORD`)

The cleanup script writes textfile metrics to `monitoring/textfile/infra_guard.prom`
(default of `--metrics-file`). node-exporter serves them through its textfile collector
(with default host collectors disabled, so it exposes only Infra-Guard metrics) and
Prometheus scrapes them via the `node` job. Grafana includes the pre-provisioned
"Infra-Guard Overview" dashboard displaying resource counts, cleanup health, failure tracking,
and S3 sync status.
