"""Registry of versioned, experimentally validated SMU PM-table layouts."""

from . import phoenix, strix_halo, strix_point

TABLE = "/sys/kernel/ryzen_smu_drv/pm_table"
VERSION_PATH = "/sys/kernel/ryzen_smu_drv/pm_table_version"

PHOENIX_VERSION = phoenix.VERSION
STRIX_HALO_VERSION = strix_halo.VERSION
STRIX_POINT_VERSIONS = strix_point.VERSIONS

PROFILES = {
    phoenix.VERSION: (phoenix.SCALARS, phoenix.CORES, phoenix.NCORES),
    strix_halo.VERSION: (strix_halo.SCALARS, strix_halo.CORES,
                         strix_halo.NCORES),
}
for version in strix_point.VERSIONS:
    PROFILES[version] = (strix_point.SCALARS, strix_point.CORES,
                         strix_point.NCORES)
