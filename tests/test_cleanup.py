#!/usr/bin/env python3
import datetime as dt
import logging
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

try:
    import boto3
    import botocore
    from botocore.exceptions import ClientError
except ModuleNotFoundError:
    class ClientError(Exception):
        def __init__(self, error_response=None, operation_name=""):
            self.response = error_response or {}
            self.operation_name = operation_name
            super().__init__(str(error_response))

    botocore = MagicMock()
    botocore.exceptions = MagicMock()
    botocore.exceptions.ClientError = ClientError
    sys.modules["boto3"] = MagicMock()
    sys.modules["botocore"] = botocore
    sys.modules["botocore.exceptions"] = botocore.exceptions

import scripts.cleanup as cleanup


class TestCleanupUtils(unittest.TestCase):
    def test_memory_log_handler(self):
        handler = cleanup.MemoryLogHandler()
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        logger = logging.getLogger("test_mem")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        logger.info("line 1")
        logger.info("line 2")
        val = handler.value()
        self.assertIn("line 1", val)
        self.assertIn("line 2", val)

    def test_tags_to_dict(self):
        tags = [{"Key": "env", "Value": "prod"}, {"Key": "owner", "Value": None}]
        result = cleanup.tags_to_dict(tags)
        self.assertEqual(result["env"], "prod")
        self.assertEqual(result["owner"], "")
        self.assertEqual(cleanup.tags_to_dict(None), {})

    def test_tag_is_true(self):
        self.assertTrue(cleanup.tag_is_true({"infra-guard:skip": "true"}, "infra-guard:skip"))
        self.assertTrue(cleanup.tag_is_true({"infra-guard:skip": "True"}, "infra-guard:skip"))
        self.assertFalse(cleanup.tag_is_true({"infra-guard:skip": "false"}, "infra-guard:skip"))
        self.assertFalse(cleanup.tag_is_true({"infra-guard:skip": None}, "infra-guard:skip"))
        self.assertFalse(cleanup.tag_is_true({}, "infra-guard:skip"))

    def test_matches_filter(self):
        tags = {"Project": "Infra-Guard", "Stage": "dev"}
        self.assertTrue(cleanup.matches_filter(tags, None, None))
        self.assertTrue(cleanup.matches_filter(tags, "Project", None))
        self.assertTrue(cleanup.matches_filter(tags, "Project", "Infra-Guard"))
        self.assertFalse(cleanup.matches_filter(tags, "Project", "Other"))
        self.assertFalse(cleanup.matches_filter(tags, "Owner", None))

    def test_older_than(self):
        now = cleanup.utcnow()
        old_time = now - dt.timedelta(days=10)
        recent_time = now - dt.timedelta(hours=1)
        self.assertTrue(cleanup.older_than(old_time, days=7))
        self.assertFalse(cleanup.older_than(recent_time, days=7))

        naive_old = old_time.replace(tzinfo=None)
        self.assertTrue(cleanup.older_than(naive_old, days=7))

    def test_stopped_at(self):
        instance = {"StateTransitionReason": "User initiated (2026-10-01 12:00:00 GMT)"}
        t = cleanup.stopped_at(instance)
        self.assertIsNotNone(t)
        self.assertEqual(t.year, 2026)
        self.assertEqual(t.month, 10)
        self.assertEqual(t.day, 1)

        self.assertIsNone(cleanup.stopped_at({"StateTransitionReason": None}))
        self.assertIsNone(cleanup.stopped_at({"StateTransitionReason": "Normal shutdown"}))
        self.assertIsNone(cleanup.stopped_at({}))

    def test_apply_action_dry_run(self):
        action = MagicMock()
        res = cleanup.apply_action("Test dry run", dry_run=True, action=action)
        self.assertTrue(res)
        action.assert_not_called()

    def test_apply_action_confirm_success(self):
        action = MagicMock()
        res = cleanup.apply_action("Test confirm", dry_run=False, action=action)
        self.assertTrue(res)
        action.assert_called_once()

    def test_apply_action_confirm_failure(self):
        action = MagicMock(side_effect=ClientError({"Error": {"Code": "400", "Message": "fail"}}, "delete"))
        res = cleanup.apply_action("Test fail", dry_run=False, action=action)
        self.assertFalse(res)

    def test_run_cleanup(self):
        action_1 = MagicMock()
        action_2 = MagicMock()
        action_3 = MagicMock()

        items = [
            ("vol-1", "Delete vol-1", action_1, {"infra-guard:skip": "true"}),
            ("vol-2", "Delete vol-2", action_2, {"env": "prod"}),
            ("vol-3", "Delete vol-3", action_3, {"env": "dev"}),
        ]

        # Dry run with tag filter env=prod
        acted, failed = cleanup.run_cleanup(items, dry_run=True, tag_key="env", tag_value="prod")
        self.assertEqual(acted, 1)
        self.assertEqual(failed, 0)
        action_2.assert_not_called()

        # Confirm run without tag filter
        acted, failed = cleanup.run_cleanup(items, dry_run=False, tag_key=None, tag_value=None)
        self.assertEqual(acted, 2)
        self.assertEqual(failed, 0)
        action_1.assert_not_called()  # skipped due to tag
        action_2.assert_called_once()
        action_3.assert_called_once()

    def test_write_prometheus_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metric_file = os.path.join(tmpdir, "metrics.prom")
            counts = {"idle_ebs_volumes": 3, "unused_elastic_ips": 1}
            cleanup.write_prometheus_metrics(metric_file, counts, failed=0, dry_run=True)

            self.assertTrue(os.path.exists(metric_file))
            with open(metric_file) as f:
                content = f.read()
            self.assertIn("infra_guard_idle_resources_total 4", content)
            self.assertIn("infra_guard_idle_ebs_volumes 3", content)
            self.assertIn("infra_guard_cleanup_failures_total 0", content)
            self.assertIn("infra_guard_cleanup_success 1", content)
            self.assertIn("infra_guard_last_run_dry_run 1", content)

    def test_upload_log_to_s3(self):
        s3 = MagicMock()
        # No bucket
        self.assertTrue(cleanup.upload_log_to_s3(s3, bucket=None, prefix="logs", body="log", dry_run=False))
        s3.put_object.assert_not_called()

        # Dry run
        self.assertTrue(cleanup.upload_log_to_s3(s3, bucket="my-bucket", prefix="logs", body="log", dry_run=True))
        s3.put_object.assert_not_called()

        # Confirm
        self.assertTrue(cleanup.upload_log_to_s3(s3, bucket="my-bucket", prefix="logs", body="log", dry_run=False))
        s3.put_object.assert_called_once()

    def test_find_ebs_volumes(self):
        ec2 = MagicMock()
        paginator = MagicMock()
        ec2.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {
                "Volumes": [
                    {
                        "VolumeId": "vol-old",
                        "CreateTime": cleanup.utcnow() - dt.timedelta(days=2),
                        "Tags": [{"Key": "Name", "Value": "test"}],
                    },
                    {
                        "VolumeId": "vol-new",
                        "CreateTime": cleanup.utcnow() + dt.timedelta(hours=1),
                        "Tags": [],
                    },
                ]
            }
        ]
        candidates = list(cleanup.find_ebs_volumes(ec2, min_age_hours=24))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], "vol-old")
        self.assertIn("Delete unattached EBS volume vol-old", candidates[0][1])

    def test_find_elastic_ips(self):
        ec2 = MagicMock()
        ec2.describe_addresses.return_value = {
            "Addresses": [
                {"AllocationId": "eipalloc-unused"},
                {"AllocationId": "eipalloc-used", "InstanceId": "i-123"},
                {"AllocationId": None},
            ]
        }
        candidates = list(cleanup.find_elastic_ips(ec2))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], "eipalloc-unused")

    def test_find_stopped_instances(self):
        ec2 = MagicMock()
        paginator = MagicMock()
        ec2.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-eligible",
                                "Tags": [{"Key": "infra-guard:cleanup", "Value": "true"}],
                                "StateTransitionReason": "User initiated (2026-09-01 10:00:00 GMT)",
                            },
                            {
                                "InstanceId": "i-no-cleanup-tag",
                                "Tags": [],
                                "StateTransitionReason": "User initiated (2026-09-01 10:00:00 GMT)",
                            },
                        ]
                    }
                ]
            }
        ]
        candidates = list(cleanup.find_stopped_instances(ec2, min_age_days=7))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], "i-eligible")

    def test_find_orphaned_security_groups(self):
        ec2 = MagicMock()
        eni_paginator = MagicMock()
        sg_paginator = MagicMock()
        ec2.get_paginator.side_effect = lambda name: eni_paginator if name == "describe_network_interfaces" else sg_paginator
        eni_paginator.paginate.return_value = [
            {"NetworkInterfaces": [{"Groups": [{"GroupId": "sg-attached"}]}]}
        ]
        sg_paginator.paginate.return_value = [
            {
                "SecurityGroups": [
                    {"GroupId": "sg-default", "GroupName": "default"},
                    {"GroupId": "sg-attached", "GroupName": "custom"},
                    {"GroupId": "sg-has-rules", "GroupName": "custom", "IpPermissions": [{"FromPort": 80}]},
                    {"GroupId": "sg-orphan", "GroupName": "custom", "IpPermissions": []},
                ]
            }
        ]
        candidates = list(cleanup.find_orphaned_security_groups(ec2))
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0][0], "sg-orphan")


if __name__ == "__main__":
    unittest.main()
