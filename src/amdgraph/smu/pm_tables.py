"""Registry of versioned, experimentally validated SMU PM-table layouts."""

from dataclasses import dataclass
from typing import Optional, Tuple

from ..model import FieldMap

from . import phoenix, strix_halo, strix_point

TABLE = "/sys/kernel/ryzen_smu_drv/pm_table"
VERSION_PATH = "/sys/kernel/ryzen_smu_drv/pm_table_version"

PHOENIX_VERSION = phoenix.VERSION
STRIX_HALO_VERSION = strix_halo.VERSION
STRIX_POINT_VERSIONS = strix_point.VERSIONS


@dataclass(frozen=True)
class PmTableLayout:
    """Everything the generic decoder needs to know about one table ABI."""

    versions: Tuple[int, ...]
    scalars: FieldMap
    cores: FieldMap
    core_slots: int
    table_floats: Optional[int] = None
    thermal_clusters: Tuple[Tuple[str, str], ...] = ()
    provenance: str = "measured"


PHOENIX = PmTableLayout((phoenix.VERSION,), phoenix.SCALARS, phoenix.CORES,
                        phoenix.NCORES)
STRIX_HALO = PmTableLayout(
    (strix_halo.VERSION,), strix_halo.SCALARS, strix_halo.CORES,
    strix_halo.NCORES,
    thermal_clusters=(("thm_core0", "thm_core0_lim"),
                      ("thm_core1", "thm_core1_lim")))
STRIX_POINT = PmTableLayout(
    tuple(strix_point.VERSIONS), strix_point.SCALARS, strix_point.CORES,
    strix_point.NCORES,
    thermal_clusters=(("thm_core0", "thm_core0_lim"),
                      ("thm_core1", "thm_core1_lim")),
    provenance="source-derived")

PROFILES = {version: PHOENIX for version in PHOENIX.versions}
PROFILES.update({version: STRIX_HALO for version in STRIX_HALO.versions})
for version in strix_point.VERSIONS:
    PROFILES[version] = STRIX_POINT
