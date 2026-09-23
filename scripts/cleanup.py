#!/usr/bin/env python3
import argparse
import datetime as dt
import logging
import logging.handlers
import os
import re
import sys
from typing import Dict, Iterable, Optional, Set, Tuple

import boto3
from botocore.exceptions import ClientError


SKIP_TAG = "infra-guard:skip"
CLEANUP_TAG = "infra-guard:cleanup"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class MemoryLogHandler(logging.handlers.BufferingHandler):
    def value(self) -> str:
        return "\n".join(self.format(record) for record in self.buffer)


def configure_logging() -> MemoryLogHandler:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    memory = MemoryLogHandler()
    memory.setFormatter(formatter)

    root.addHandler(console)
    root.addHandler(memory)
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


def tags_to_dict(tags: Optional[Iterable[Dict[str, str]]]) -> Dict[str, str]:
    return {tag.get("Key", ""): tag.get("Value", "") for tag in tags or []}


def has_skip_tag(tags: Dict[str, str]) -> bool:
    return tags.get(SKIP_TAG, "").lower() == "true"


def has_cleanup_tag(tags: Dict[str, str]) -> bool:
    return tags.get(CLEANUP_TAG, "").lower() == "true"


def matches_resource_tag_filter(tags: Dict[str, str], tag_key: Optional[str], tag_value: Optional[str]) -> bool:
    if not tag_key:
        return True
    if tag_key not in tags:
        return False
    if tag_value is None:
        return True
    return tags.get(tag_key) == tag_value


def older_than(timestamp: dt.datetime, **kwargs: int) -> bool:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    return timestamp <= utcnow() - dt.timedelta(**kwargs)


def stopped_at(instance: Dict) -> Optional[dt.datetime]:
    reason = instance.get("StateTransitionReason", "")
    match = re.search(r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) GMT\)", reason)
    if not match:
        return None
    return dt.datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)


def apply_action(description: str, dry_run: bool, action) -> bool:
    if dry_run:
        logging.info("[DRY-RUN] %s", description)
        return True

    try:
        action()
        logging.info("%s", description)
        return True
    except ClientError as exc:
        logging.error("Failed: %s: %s", description, exc)
        return False


def cleanup_ebs_volumes(
    ec2,
    dry_run: bool,
    min_age_hours: int,
    tag_key: Optional[str],
    tag_value: Optional[str],
) -> Tuple[int, int]:
    logging.info("Scanning unattached EBS volumes older than %s hours", min_age_hours)
    acted = 0
    failed = 0
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for volume in page.get("Volumes", []):
            volume_id = volume["VolumeId"]
            tags = tags_to_dict(volume.get("Tags"))
            if not matches_resource_tag_filter(tags, tag_key, tag_value):
                continue
            if has_skip_tag(tags):
                logging.info("Skipping %s because %s=true", volume_id, SKIP_TAG)
                continue
            if not older_than(volume["CreateTime"], hours=min_age_hours):
                logging.info("Skipping %s because it is newer than threshold", volume_id)
                continue
            if apply_action(
                f"Delete unattached EBS volume {volume_id}",
                dry_run,
                lambda volume_id=volume_id: ec2.delete_volume(VolumeId=volume_id),
            ):
                acted += 1
            else:
                failed += 1
    return acted, failed


def cleanup_elastic_ips(ec2, dry_run: bool, tag_key: Optional[str], tag_value: Optional[str]) -> Tuple[int, int]:
    logging.info("Scanning unused Elastic IP addresses")
    acted = 0
    failed = 0
    for address in ec2.describe_addresses().get("Addresses", []):
        if address.get("InstanceId") or address.get("NetworkInterfaceId"):
            continue
        allocation_id = address.get("AllocationId")
        if not allocation_id:
            logging.info("Skipping EC2-Classic address without AllocationId")
            continue
        tags = tags_to_dict(address.get("Tags"))
        if not matches_resource_tag_filter(tags, tag_key, tag_value):
            continue
        if has_skip_tag(tags):
            logging.info("Skipping %s because %s=true", allocation_id, SKIP_TAG)
            continue
        if apply_action(
            f"Release unused Elastic IP {allocation_id}",
            dry_run,
            lambda allocation_id=allocation_id: ec2.release_address(AllocationId=allocation_id),
        ):
            acted += 1
        else:
            failed += 1
    return acted, failed


def cleanup_stopped_instances(
    ec2,
    dry_run: bool,
    min_age_days: int,
    tag_key: Optional[str],
    tag_value: Optional[str],
) -> Tuple[int, int]:
    logging.info("Scanning stopped EC2 instances older than %s days", min_age_days)
    acted = 0
    failed = 0
    paginator = ec2.get_paginator("describe_instances")
    filters = [{"Name": "instance-state-name", "Values": ["stopped"]}]
    for page in paginator.paginate(Filters=filters):
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                instance_id = instance["InstanceId"]
                tags = tags_to_dict(instance.get("Tags"))
                if not matches_resource_tag_filter(tags, tag_key, tag_value):
                    continue
                if has_skip_tag(tags):
                    logging.info("Skipping %s because %s=true", instance_id, SKIP_TAG)
                    continue
                if not has_cleanup_tag(tags):
                    logging.info("Skipping %s because %s=true is required", instance_id, CLEANUP_TAG)
                    continue
                stop_time = stopped_at(instance)
                if stop_time is None:
                    logging.info("Skipping %s because its stop time cannot be determined", instance_id)
                    continue
                if not older_than(stop_time, days=min_age_days):
                    logging.info("Skipping %s because it is newer than threshold", instance_id)
                    continue
                if apply_action(
                    f"Terminate stopped EC2 instance {instance_id} (stopped at {stop_time:%Y-%m-%d %H:%M:%S} UTC)",
                    dry_run,
                    lambda instance_id=instance_id: ec2.terminate_instances(InstanceIds=[instance_id]),
                ):
                    acted += 1
                else:
                    failed += 1
    return acted, failed


def ami_snapshot_ids(ec2) -> Set[str]:
    protected: Set[str] = set()
    paginator = ec2.get_paginator("describe_images")
    for page in paginator.paginate(Owners=["self"]):
        for image in page.get("Images", []):
            for mapping in image.get("BlockDeviceMappings", []):
                snapshot_id = mapping.get("Ebs", {}).get("SnapshotId")
                if snapshot_id:
                    protected.add(snapshot_id)
    return protected


def cleanup_old_snapshots(
    ec2,
    dry_run: bool,
    min_age_days: int,
    tag_key: Optional[str],
    tag_value: Optional[str],
) -> Tuple[int, int]:
    logging.info("Scanning owned EBS snapshots older than %s days", min_age_days)
    acted = 0
    failed = 0
    protected = ami_snapshot_ids(ec2)
    paginator = ec2.get_paginator("describe_snapshots")
    for page in paginator.paginate(OwnerIds=["self"]):
        for snapshot in page.get("Snapshots", []):
            snapshot_id = snapshot["SnapshotId"]
            tags = tags_to_dict(snapshot.get("Tags"))
            if not matches_resource_tag_filter(tags, tag_key, tag_value):
                continue
            if has_skip_tag(tags) or tags.get("keep", "").lower() == "true":
                logging.info("Skipping %s because it is protected by tag", snapshot_id)
                continue
            if snapshot_id in protected:
                logging.info("Skipping %s because an owned AMI references it", snapshot_id)
                continue
            if not older_than(snapshot["StartTime"], days=min_age_days):
                logging.info("Skipping %s because it is newer than threshold", snapshot_id)
                continue
            if apply_action(
                f"Delete old EBS snapshot {snapshot_id}",
                dry_run,
                lambda snapshot_id=snapshot_id: ec2.delete_snapshot(SnapshotId=snapshot_id),
            ):
                acted += 1
            else:
                failed += 1
    return acted, failed


def attached_security_group_ids(ec2) -> Set[str]:
    group_ids: Set[str] = set()
    paginator = ec2.get_paginator("describe_network_interfaces")
    for page in paginator.paginate():
        for eni in page.get("NetworkInterfaces", []):
            for group in eni.get("Groups", []):
                group_ids.add(group["GroupId"])
    return group_ids


def cleanup_orphaned_security_groups(ec2, dry_run: bool, tag_key: Optional[str], tag_value: Optional[str]) -> Tuple[int, int]:
    logging.info("Scanning orphaned security groups")
    acted = 0
    failed = 0
    attached = attached_security_group_ids(ec2)
    paginator = ec2.get_paginator("describe_security_groups")
    for page in paginator.paginate():
        for group in page.get("SecurityGroups", []):
            group_id = group["GroupId"]
            tags = tags_to_dict(group.get("Tags"))
            if group.get("GroupName") == "default":
                continue
            if group_id in attached:
                continue
            if has_skip_tag(tags):
                logging.info("Skipping %s because %s=true", group_id, SKIP_TAG)
                continue
            if not matches_resource_tag_filter(tags, tag_key, tag_value):
                continue
            if group.get("IpPermissions"):
                logging.info("Skipping %s because ingress rules still exist", group_id)
                continue
            if apply_action(
                f"Delete orphaned security group {group_id}",
                dry_run,
                lambda group_id=group_id: ec2.delete_security_group(GroupId=group_id),
            ):
                acted += 1
            else:
                failed += 1
    return acted, failed


def write_prometheus_metrics(path: str, counts: Dict[str, int], dry_run: bool) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = [
        "# HELP infra_guard_idle_resources_total Idle resources found by the latest Infra-Guard run.",
        "# TYPE infra_guard_idle_resources_total gauge",
        f"infra_guard_idle_resources_total {sum(counts.values())}",
    ]
    for name, count in sorted(counts.items()):
        lines.extend(
            [
                f"# HELP infra_guard_{name} {name.replace('_', ' ')} found by the latest Infra-Guard run.",
                f"# TYPE infra_guard_{name} gauge",
                f"infra_guard_{name} {count}",
            ]
        )
    lines.extend(
        [
            "# HELP infra_guard_last_run_timestamp Unix timestamp of the latest Infra-Guard cleanup run.",
            "# TYPE infra_guard_last_run_timestamp gauge",
            f"infra_guard_last_run_timestamp {int(utcnow().timestamp())}",
            "# HELP infra_guard_last_run_dry_run Whether the latest Infra-Guard run was dry-run mode.",
            "# TYPE infra_guard_last_run_dry_run gauge",
            f"infra_guard_last_run_dry_run {1 if dry_run else 0}",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as metrics_file:
        metrics_file.write("\n".join(lines))
    logging.info("Wrote Prometheus metrics to %s", path)


def upload_log_to_s3(s3, bucket: Optional[str], prefix: str, body: str, dry_run: bool) -> None:
    if not bucket:
        logging.info("No cleanup log bucket configured; skipping S3 log upload")
        return
    key = f"{prefix.rstrip('/')}/cleanup-{utcnow().strftime('%Y%m%dT%H%M%SZ')}.log"
    if dry_run:
        logging.info("[DRY-RUN] Upload cleanup log to s3://%s/%s", bucket, key)
        return
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ServerSideEncryption="AES256",
        ContentType="text/plain",
    )
    logging.info("Uploaded cleanup log to s3://%s/%s", bucket, key)


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

    session = boto3.Session(region_name=args.region)
    ec2 = session.client("ec2")
    s3 = session.client("s3")

    logging.info("Infra-Guard cleanup starting; mode=%s", "dry-run" if dry_run else "confirm")
    if args.resource_tag_key:
        logging.info(
            "Resource cleanup limited to tag %s=%s",
            args.resource_tag_key,
            args.resource_tag_value if args.resource_tag_value is not None else "*",
        )
    results = {
        "idle_ebs_volumes": cleanup_ebs_volumes(ec2, dry_run, args.ebs_min_age_hours, args.resource_tag_key, args.resource_tag_value),
        "unused_elastic_ips": cleanup_elastic_ips(ec2, dry_run, args.resource_tag_key, args.resource_tag_value),
        "stopped_instances": cleanup_stopped_instances(
            ec2,
            dry_run,
            args.stopped_instance_min_age_days,
            args.resource_tag_key,
            args.resource_tag_value,
        ),
        "old_snapshots": cleanup_old_snapshots(ec2, dry_run, args.snapshot_min_age_days, args.resource_tag_key, args.resource_tag_value),
        "orphaned_security_groups": cleanup_orphaned_security_groups(ec2, dry_run, args.resource_tag_key, args.resource_tag_value),
    }
    counts = {name: acted for name, (acted, _) in results.items()}
    failed = sum(failed for _, failed in results.values())
    write_prometheus_metrics(args.metrics_file, counts, dry_run)

    log_body = memory_log.value()
    upload_log_to_s3(s3, args.log_bucket, args.log_prefix, log_body, dry_run)

    if failed:
        logging.error("Infra-Guard cleanup completed with %s failed action(s)", failed)
        return 1
    logging.info("Infra-Guard cleanup completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
