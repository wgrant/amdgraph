"""Registry of versioned, experimentally validated SMU PM-table layouts."""

from . import phoenix, strix_halo

TABLE = "/sys/kernel/ryzen_smu_drv/pm_table"
VERSION_PATH = "/sys/kernel/ryzen_smu_drv/pm_table_version"

PHOENIX_VERSION = phoenix.VERSION
STRIX_HALO_VERSION = strix_halo.VERSION

PROFILES = {
    phoenix.VERSION: (phoenix.SCALARS, phoenix.CORES, phoenix.NCORES),
    strix_halo.VERSION: (strix_halo.SCALARS, strix_halo.CORES,
                         strix_halo.NCORES),
}
