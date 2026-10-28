#!/usr/bin/env python3
"""Runnable entry point: python3 run.py <command>. Offline only."""
import sys
from earthinstall.cli import main
if __name__ == "__main__":
    sys.exit(main())
