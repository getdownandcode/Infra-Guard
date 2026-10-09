#!/usr/bin/env python3
import argparse
import datetime as dt
import logging
import os
import re
import sys
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

try:
    import boto3
    from botocore.exceptions import ClientError
except ModuleNotFoundError:
    boto3 = None  # type: ignore
    ClientError = Exception  # type: ignore

SKIP_TAG = "infra-guard:skip"
CLEANUP_TAG = "infra-guard:cleanup"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class MemoryLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.buffer: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.buffer.append(self.format(record))

    def value(self) -> str:
        return "\n".join(self.buffer)


def configure_logging() -> MemoryLogHandler:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    memory = MemoryLogHandler()
    for handler in (logging.StreamHandler(sys.stdout), memory):
        handler.setFormatter(formatter)
        root.addHandler(handler)
    return memory


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Infra-Guard AWS idle resource cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without mutating AWS")
    parser.add_argument("--confirm", action="store_true", help="Delete or release eligible resources")
    parser.add_argument("--region", default=None, help="AWS region override")
    parser.add_argument("--log-bucket", default=None, help="S3 bucket for cleanup logs")
    parser.add_argument("--log-prefix", default="cleanup-logs", help="S3 prefix for cleanup logs")
    parser.add_argument("--ebs-min-age-hours", type=int, default=24)
    parser.add_argument("--stopped-instance-min-age-days", type=int, default=7)
    parser.add_argument("--snapshot-min-age-days", type=int, default=30)
    parser.add_argument("--resource-tag-key", default=None, help="Only clean resources with this tag key")
    parser.add_argument("--resource-tag-value", default=None, help="Optional value required for --resource-tag-key")
    parser.add_argument(
        "--metrics-file",
        default=os.path.join("monitoring", "textfile", "infra_guard.prom"),
        help="Prometheus textfile metrics output path",
    )
    return parser.parse_args()


def tags_to_dict(tags: Optional[Iterable[Dict[str, Any]]]) -> Dict[str, str]:
    return {str(t["Key"]): str(t.get("Value") or "") for t in tags or [] if t.get("Key")}


def tag_is_true(tags: Dict[str, str], key: str) -> bool:
    val = tags.get(key)
    return str(val).lower() == "true" if val is not None else False


def matches_filter(tags: Dict[str, str], key: Optional[str], value: Optional[str]) -> bool:
    if not key:
        return True
    return key in tags and (value is None or tags.get(key) == value)


def older_than(timestamp: dt.datetime, **kwargs: int) -> bool:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    return timestamp <= utcnow() - dt.timedelta(**kwargs)


def stopped_at(instance: Dict) -> Optional[dt.datetime]:
    reason = instance.get("StateTransitionReason") or ""
    match = re.search(r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) GMT\)", reason)
    return dt.datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc) if match else None


def apply_action(desc: str, dry_run: bool, action: Callable[[], Any]) -> bool:
    if dry_run:
        logging.info("[DRY-RUN] %s", desc)
        return True
    try:
        action()
        logging.info("%s", desc)
        return True
    except ClientError as exc:
        logging.error("Failed: %s: %s", desc, exc)
        return False


def run_cleanup(
    items: Iterable[Tuple[str, str, Callable[[], Any], Dict[str, str]]],
    dry_run: bool,
    tag_key: Optional[str],
    tag_value: Optional[str],
) -> Tuple[int, int]:
    acted, failed = 0, 0
    for res_id, desc, action, tags in items:
        if not matches_filter(tags, tag_key, tag_value):
            continue
        if tag_is_true(tags, SKIP_TAG):
            logging.info("Skipping %s because %s=true", res_id, SKIP_TAG)
            continue
        if apply_action(desc, dry_run, action):
            acted += 1
        else:
            failed += 1
    return acted, failed


def find_ebs_volumes(ec2, min_age_hours: int):
    logging.info("Scanning unattached EBS volumes older than %s hours", min_age_hours)
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for vol in page.get("Volumes", []):
            vid = vol["VolumeId"]
            if not older_than(vol["CreateTime"], hours=min_age_hours):
                logging.info("Skipping %s because it is newer than threshold", vid)
                continue
            yield vid, f"Delete unattached EBS volume {vid}", lambda vid=vid: ec2.delete_volume(VolumeId=vid), tags_to_dict(vol.get("Tags"))


def find_elastic_ips(ec2):
    logging.info("Scanning unused Elastic IP addresses")
    for addr in ec2.describe_addresses().get("Addresses", []):
        alloc_id = addr.get("AllocationId")
        if addr.get("InstanceId") or addr.get("NetworkInterfaceId"):
            continue
        if not alloc_id:
            logging.info("Skipping EC2-Classic address without AllocationId")
            continue
        yield alloc_id, f"Release unused Elastic IP {alloc_id}", lambda a=alloc_id: ec2.release_address(AllocationId=a), tags_to_dict(addr.get("Tags"))


def find_stopped_instances(ec2, min_age_days: int):
    logging.info("Scanning stopped EC2 instances older than %s days", min_age_days)
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate(Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]):
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                iid = inst["InstanceId"]
                tags = tags_to_dict(inst.get("Tags"))
                if not tag_is_true(tags, CLEANUP_TAG):
                    logging.info("Skipping %s because %s=true is required", iid, CLEANUP_TAG)
                    continue
                stop_time = stopped_at(inst)
                if not stop_time:
                    logging.info("Skipping %s because its stop time cannot be determined", iid)
                elif not older_than(stop_time, days=min_age_days):
                    logging.info("Skipping %s because it is newer than threshold", iid)
                else:
                    desc = f"Terminate stopped EC2 instance {iid} (stopped at {stop_time:%Y-%m-%d %H:%M:%S} UTC)"
                    yield iid, desc, lambda i=iid: ec2.terminate_instances(InstanceIds=[i]), tags


def find_old_snapshots(ec2, min_age_days: int):
    logging.info("Scanning owned EBS snapshots older than %s days", min_age_days)
    protected = {
        m["Ebs"]["SnapshotId"]
        for page in ec2.get_paginator("describe_images").paginate(Owners=["self"])
        for img in page.get("Images", [])
        for m in img.get("BlockDeviceMappings", [])
        if m.get("Ebs", {}).get("SnapshotId")
    }
    for page in ec2.get_paginator("describe_snapshots").paginate(OwnerIds=["self"]):
        for snap in page.get("Snapshots", []):
            sid = snap["SnapshotId"]
            tags = tags_to_dict(snap.get("Tags"))
            if tag_is_true(tags, "keep"):
                logging.info("Skipping %s because it is protected by tag", sid)
            elif sid in protected:
                logging.info("Skipping %s because an owned AMI references it", sid)
            elif not older_than(snap["StartTime"], days=min_age_days):
                logging.info("Skipping %s because it is newer than threshold", sid)
            else:
                yield sid, f"Delete old EBS snapshot {sid}", lambda s=sid: ec2.delete_snapshot(SnapshotId=s), tags


def find_orphaned_security_groups(ec2):
    logging.info("Scanning orphaned security groups")
    attached = {
        g["GroupId"]
        for page in ec2.get_paginator("describe_network_interfaces").paginate()
        for eni in page.get("NetworkInterfaces", [])
        for g in eni.get("Groups", [])
    }
    for page in ec2.get_paginator("describe_security_groups").paginate():
        for grp in page.get("SecurityGroups", []):
            gid = grp["GroupId"]
            if grp.get("GroupName") == "default" or gid in attached:
                continue
            if grp.get("IpPermissions"):
                logging.info("Skipping %s because ingress rules still exist", gid)
                continue
            yield gid, f"Delete orphaned security group {gid}", lambda g=gid: ec2.delete_security_group(GroupId=g), tags_to_dict(grp.get("Tags"))


def write_prometheus_metrics(path: str, counts: Dict[str, int], failed: int, dry_run: bool) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# HELP infra_guard_idle_resources_total Idle resources found by the latest Infra-Guard run.",
        "# TYPE infra_guard_idle_resources_total gauge",
        f"infra_guard_idle_resources_total {sum(counts.values())}",
    ]
    for name, count in sorted(counts.items()):
        lines.extend([
            f"# HELP infra_guard_{name} {name.replace('_', ' ')} found by the latest Infra-Guard run.",
            f"# TYPE infra_guard_{name} gauge",
            f"infra_guard_{name} {count}",
        ])
    lines.extend([
        "# HELP infra_guard_cleanup_failures_total Total failed cleanup actions in the latest Infra-Guard run.",
        "# TYPE infra_guard_cleanup_failures_total gauge",
        f"infra_guard_cleanup_failures_total {failed}",
        "# HELP infra_guard_cleanup_success Whether the latest Infra-Guard run completed without failures.",
        "# TYPE infra_guard_cleanup_success gauge",
        f"infra_guard_cleanup_success {1 if failed == 0 else 0}",
        "# HELP infra_guard_last_run_timestamp Unix timestamp of the latest Infra-Guard cleanup run.",
        "# TYPE infra_guard_last_run_timestamp gauge",
        f"infra_guard_last_run_timestamp {int(utcnow().timestamp())}",
        "# HELP infra_guard_last_run_dry_run Whether the latest Infra-Guard run was dry-run mode.",
        "# TYPE infra_guard_last_run_dry_run gauge",
        f"infra_guard_last_run_dry_run {1 if dry_run else 0}\n",
    ])
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp_path, path)
    logging.info("Wrote Prometheus metrics to %s", path)


def upload_log_to_s3(s3, bucket: Optional[str], prefix: str, body: str, dry_run: bool) -> bool:
    if not bucket:
        logging.info("No cleanup log bucket configured; skipping S3 log upload")
        return True
    key = f"{prefix.rstrip('/')}/cleanup-{utcnow().strftime('%Y%m%dT%H%M%SZ')}.log"
    if dry_run:
        logging.info("[DRY-RUN] Upload cleanup log to s3://%s/%s", bucket, key)
        return True
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"), ServerSideEncryption="AES256", ContentType="text/plain")
        logging.info("Uploaded cleanup log to s3://%s/%s", bucket, key)
        return True
    except ClientError as exc:
        logging.error("Failed to upload cleanup log to s3://%s/%s: %s", bucket, key, exc)
        return False


def main() -> int:
    args = get_args()
    memory_log = configure_logging()
    if args.confirm and args.dry_run:
        logging.error("Use either --dry-run or --confirm, not both")
        return 2
    if args.resource_tag_value is not None and not args.resource_tag_key:
        logging.error("--resource-tag-value requires --resource-tag-key")
        return 2

    dry_run = not args.confirm
    if boto3 is None:
        logging.error("boto3 is required to connect to AWS. Install dependencies: pip install -r requirements.txt")
        return 2

    session = boto3.Session(region_name=args.region)
    ec2, s3 = session.client("ec2"), session.client("s3")

    logging.info("Infra-Guard cleanup starting; mode=%s", "dry-run" if dry_run else "confirm")
    if args.resource_tag_key:
        val = args.resource_tag_value if args.resource_tag_value is not None else "*"
        logging.info("Resource cleanup limited to tag %s=%s", args.resource_tag_key, val)

    scanners = {
        "idle_ebs_volumes": find_ebs_volumes(ec2, args.ebs_min_age_hours),
        "unused_elastic_ips": find_elastic_ips(ec2),
        "stopped_instances": find_stopped_instances(ec2, args.stopped_instance_min_age_days),
        "old_snapshots": find_old_snapshots(ec2, args.snapshot_min_age_days),
        "orphaned_security_groups": find_orphaned_security_groups(ec2),
    }
    results = {name: run_cleanup(items, dry_run, args.resource_tag_key, args.resource_tag_value) for name, items in scanners.items()}

    counts = {name: acted for name, (acted, _) in results.items()}
    failed = sum(f for _, f in results.values())
    write_prometheus_metrics(args.metrics_file, counts, failed, dry_run)

    exit_code = 1 if failed else 0
    if failed:
        logging.error("Infra-Guard cleanup completed with %s failed action(s)", failed)
    else:
        logging.info("Infra-Guard cleanup completed successfully")

    upload_log_to_s3(s3, args.log_bucket, args.log_prefix, memory_log.value(), dry_run)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
