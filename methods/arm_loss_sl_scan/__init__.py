"""arm_loss_sl_scan — SL -> arm-loss -> indication discovery (find-mode) scan.

DISCOVERY nomination, NOT a verdict input. Federates to the target-contracts eval-ledger via
input_manifest_ids. See scan.py (pure core) and cli.py (S3 plumbing + federation sidecar)."""
from .scan import (
    BYSTANDER_MAP_COLUMNS,
    METHOD_VERSION,
    SCAN_COLUMNS,
    bystander_map,
    sl_arm_scan,
)

__all__ = ["sl_arm_scan", "bystander_map", "SCAN_COLUMNS", "BYSTANDER_MAP_COLUMNS", "METHOD_VERSION"]
