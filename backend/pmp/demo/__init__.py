"""demo.

Synthetic plant data for development and demonstrations (plan sub-phase 1.4): a
deterministic simulator of the demo plant with the wireframe fault story, history
loaded through the history import, and a live replay that plays the OT gateway.

SYNTHETIC DATA: proves the software, not detection on real equipment (AC-04).

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.demo.generator import DEFAULT_SEED, PlantSimulator, batches_for_minute, default_anchor
from pmp.demo.history import demo_tags, load_history, write_history_files
from pmp.demo.live import ReplayStats, post_json, replay
from pmp.demo.model import DemoTag

__all__ = [
    "DEFAULT_SEED",
    "DemoTag",
    "PlantSimulator",
    "ReplayStats",
    "batches_for_minute",
    "default_anchor",
    "demo_tags",
    "load_history",
    "post_json",
    "replay",
    "write_history_files",
]
