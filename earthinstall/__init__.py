"""Earth Upgrade & Rescue — offline-first installer/recovery planner for Redmi 12C (earth).

This package NEVER touches the phone. It performs offline verification, planning,
and simulation only. There is no code path that invokes adb, fastboot, mtkclient,
or any block device. See earthinstall.safety for the enforced invariants.
"""

__version__ = "0.1.0-offline"
