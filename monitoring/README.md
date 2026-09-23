# Infra-Guard Monitoring

Minimal Prometheus + Grafana stack that scrapes the metrics written by the cleanup script.

- `docker-compose.yml` — Prometheus, node_exporter (textfile collector), Grafana
- `prometheus.yml` — scrape configuration
- `grafana/provisioning/` — auto-provisioned Prometheus datasource

## Run

```bash
docker compose up -d
```

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (defaults to `admin`/`admin`, override with `GRAFANA_USER`/`GRAFANA_PASSWORD`)

The cleanup script writes textfile metrics to `monitoring/textfile/infra_guard.prom`
(default of `--metrics-file`). node_exporter serves them through its textfile collector
(with default host collectors disabled, so it exposes only Infra-Guard metrics) and
Prometheus scrapes them via the `node` job. Metric names are unchanged, e.g. query
`infra_guard_idle_resources_total` directly in Grafana.
