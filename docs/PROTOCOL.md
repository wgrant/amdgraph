# History service protocol

`amdgraphd` listens on a mode-0600 Unix domain socket. Messages are compact
JSON objects terminated by a newline. Protocol version 1 has four server event
types:

- `hello`: protocol version, interval, metadata, and supported metric keys.
- `snapshot`: ordered `[monotonic_time, values]` samples plus markers and
  metadata. The initial snapshot is the newest hour by default.
- `sample`: one live sample. It is queued after the snapshot, so there is no
  history/live gap.
- `marker` and `recording`: state changes broadcast or acknowledged by the
  server.

Clients may send `snapshot` with optional `start`/`end`, `mark`, `cap_rate`,
`record_start`, and `record_stop`. Unknown metric keys must be retained;
unknown message types may be ignored. A different `hello.protocol` is a hard
compatibility failure.

Each client has a bounded 128-message output queue. A client that cannot keep
up is dropped rather than being allowed to delay hardware sampling or other
clients. Reconnecting clients request a fresh snapshot before accepting the
new live stream.

Times are monotonic within the persisted history. SQLite also records a wall
clock alongside every sample for future correlation and migration, without
making wall-clock adjustments distort chart intervals.
