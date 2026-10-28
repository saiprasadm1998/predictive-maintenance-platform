"""diagnostics.

Signal contributions, failure-mode signature matching and similar cases.

Public interface of the module (ARC-001 §4.1). Other modules may import only
what this file exports, never the module's internal files.
"""

from pmp.diagnostics.domain import (
    DEFAULT_Z_REF,
    Direction,
    LibraryError,
    ModeMatch,
    ModeSpec,
    Reading,
    Symptom,
    SymptomMatch,
    SymptomResult,
    agreement,
    check_mode,
    match_mode,
    rank,
)
from pmp.diagnostics.service import (
    Diagnosis,
    ModeDiagnosis,
    ModeView,
    diagnose,
    import_library,
    list_modes,
    mode_from_dict,
    mode_history,
    retire_mode,
    save_mode,
)

__all__ = [
    "DEFAULT_Z_REF",
    "Diagnosis",
    "Direction",
    "LibraryError",
    "ModeDiagnosis",
    "ModeMatch",
    "ModeSpec",
    "ModeView",
    "Reading",
    "Symptom",
    "SymptomMatch",
    "SymptomResult",
    "agreement",
    "check_mode",
    "diagnose",
    "import_library",
    "list_modes",
    "match_mode",
    "mode_from_dict",
    "mode_history",
    "rank",
    "retire_mode",
    "save_mode",
]
