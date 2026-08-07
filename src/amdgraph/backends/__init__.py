"""Layer 1 -- hardware backends.

Each module here owns one hardware family and decides for itself whether it
applies to the running machine. `Sampler` (layer 2) discovers which backends
apply and composes their output into one sample dict; nothing above that
layer knows a backend exists -- see base.py and docs/DESIGN.md.

May import: fields, sysfs, and backends.base as a declared same-layer base
class (see tools/check-layers.py's ALLOWED_SAME_LAYER).
"""
