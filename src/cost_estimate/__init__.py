"""Internal v0.9.4 deterministic cost snapshot boundary.

Keep this initializer dependency-light because the workflow schema owns the
snapshot field while the resolver itself consumes workflow route contracts.
"""

from .models import CostEstimateSnapshotV1

__all__ = [
    "CostEstimateSnapshotV1",
]
