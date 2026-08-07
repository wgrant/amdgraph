"""Layer 0 -- shared, dependency-free telemetry types."""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Mapping, Optional, Protocol, Sequence, Tuple


SampleValue = Optional[float]
Sample = Dict[str, SampleValue]
Metadata = Dict[str, str]


class MetricKind(Enum):
    SCALAR = "scalar"
    PER_CORE = "per_core"
    DERIVED = "derived"


@dataclass(frozen=True)
class Metric:
    key: str
    unit: str = ""
    kind: MetricKind = MetricKind.SCALAR
    record: bool = True


class FS(Protocol):
    def read_text(self, path: str) -> Optional[str]: ...
    def read_bytes(self, path: str) -> Optional[bytes]: ...
    def read_num(self, path: str, scale: float = 1.0) -> Optional[float]: ...
    def glob(self, pattern: str) -> Sequence[str]: ...
    def listdir(self, path: str) -> Sequence[str]: ...


class Source(Protocol):
    def sample(self) -> Sample: ...
    def notes(self) -> Sequence[str]: ...
    def meta(self) -> Metadata: ...
    def metric_keys(self) -> Sequence[str]: ...
    def set_cap_rate(self, hz: float) -> None: ...
    def reset(self) -> None: ...
    def close(self) -> None: ...


FieldMap = Mapping[str, Tuple[int, float]]
