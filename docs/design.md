# Design

goose-sqlite calls the system SQLite library through a small C adapter. It is
synchronous and has no pool, ORM, SQL builder, or implicit transaction. SQLite
is a required native dependency; there is no pure-Goose fallback.

Goose code receives opaque integer handles, not SQLite pointers. The adapter
checks each handle in a registry owned by the current OS thread. Handle copies
refer to the same resource; close or finalize invalidates every copy. Thread exit
cleans up remaining handles. These checks protect against accidental misuse,
not hostile native code in the same process.

Bindings copy their input, and byte reads copy into caller-owned arrays. Numeric
reads require the exact SQLite storage type. Callers manage transactions and
resource cleanup explicitly, and must check operation and cleanup results.

Connection policy disables extensions, untrusted schemas, PRAGMA, ATTACH/DETACH
and virtual-table creation/deletion. This limits the public SQL interface but
does not sandbox SQL, database files, filenames or other native code. The
[security page](../SECURITY.md) describes the trust boundary. The [API contract](api.md)
lists limits and error behavior.

Design references: [prepared statements](https://sqlite.org/c3ref/stmt.html),
[stepping](https://sqlite.org/c3ref/step.html), [reset](https://sqlite.org/c3ref/reset.html),
[defensive mode](https://sqlite.org/c3ref/c_dbconfig_defensive.html),
[SQLite limits](https://sqlite.org/limits.html), and
[progress handlers](https://sqlite.org/c3ref/progress_handler.html).
