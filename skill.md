# Infra-Guard: Cloud Cost & Health Optimizer
*Enterprise-grade Cloud Cost Analysis and Infrastructure Health Monitoring Suite*

## 🚀 Project Overview
Infra-Guard is a comprehensive GitOps-driven framework designed to automate cloud cost optimization and infrastructure observability. It eliminates resource wastage through automated cleanup workflows and provides real-time visibility into system health using a containerized monitoring stack.

## 🛠 Technical Architecture
- **Cloud Provider:** AWS (EC2, S3)
- **Orchestration & CI/CD:** Jenkins, GitHub, GitOps
- **Containerization:** Docker
- **Observability Stack:** Prometheus (Metrics), Grafana (Visualization)
- **Data Persistence:** AWS S3 (Versioned State Backups)

## 🌟 Key Engineering Contributions

### 🏗 GitOps-Driven Automation Pipeline
- **Architecture:** Architected a seamless CI/CD flow integrating GitHub and Jenkins, treating infrastructure state as code.
- **Cost Optimization:** Developed automated "Cleanup Workflows" that identify and terminate idle cloud resources, significantly reducing monthly AWS spend.
- **Efficiency:** Reduced manual intervention in resource provisioning by implementing declarative state synchronization.

### 📊 Containerized Observability Stack
- **Infrastructure:** Deployed a distributed monitoring layer by containerizing Prometheus and Grafana agents via Docker on AWS EC2.
- **Visualization:** Engineered custom Grafana dashboards to track CPU/Memory saturation, network latency, and cost-per-resource metrics.
- **Alerting:** Configured Prometheus alerting rules to notify stakeholders of health anomalies before they impact SLAs.

### 🛡 Disaster Recovery & State Management
- **Backup Strategy:** Implemented an automated synchronization mechanism to push infrastructure state and configuration snapshots to AWS S3.
- **Reliability:** Leveraged S3 Versioning to enable point-in-time recovery of infrastructure states, ensuring a robust Disaster Recovery (DR) posture.

## 📈 Impact & Results
- **Cost Reduction:** Lowered cloud overhead by automating the identification and removal of orphaned resources.
- **Reliability:** Reduced Mean Time to Recovery (MTTR) through versioned S3 state backups.
- **Observability:** Achieved 100% visibility into EC2 instance health and resource consumption via real-time dashboards.
