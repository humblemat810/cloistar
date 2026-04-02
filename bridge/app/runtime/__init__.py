from pathlib import Path
import sys

from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parents[3]
_KOGWISTAR_ROOT = _REPO_ROOT / "kogwistar"
if str(_KOGWISTAR_ROOT) not in sys.path:
    sys.path.insert(0, str(_KOGWISTAR_ROOT))

if not getattr(BaseModel, "_kogwistar_field_mode_compat", False):
    _orig_model_dump = BaseModel.model_dump
    _orig_model_dump_json = BaseModel.model_dump_json

    def _compat_model_dump(self, *args, **kwargs):
        kwargs.pop("field_mode", None)
        return _orig_model_dump(self, *args, **kwargs)

    def _compat_model_dump_json(self, *args, **kwargs):
        kwargs.pop("field_mode", None)
        return _orig_model_dump_json(self, *args, **kwargs)

    BaseModel.model_dump = _compat_model_dump  # type: ignore[assignment]
    BaseModel.model_dump_json = _compat_model_dump_json  # type: ignore[assignment]
    BaseModel._kogwistar_field_mode_compat = True  # type: ignore[attr-defined]

from .governance_runtime import (
    GovernanceRuntimeDecision,
    GovernanceRuntimeHost,
    GovernanceRuntimeResume,
    get_governance_runtime_host,
    reset_governance_runtime_host,
)

__all__ = [
    "GovernanceRuntimeDecision",
    "GovernanceRuntimeHost",
    "GovernanceRuntimeResume",
    "get_governance_runtime_host",
    "reset_governance_runtime_host",
]
