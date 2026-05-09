#!/usr/bin/env python3
"""Backward-compatible entry point for the Infra-Guard cleanup workflow."""

from cleanup import main


if __name__ == "__main__":
    raise SystemExit(main())
