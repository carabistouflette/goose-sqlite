// SPDX-License-Identifier: Apache-2.0
#include <charconv>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <sqlite3.h>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef USE_SQLITECPP
#include <SQLiteCpp/SQLiteCpp.h>
#endif

static void require(bool ok, const char *message) {
  if (!ok)
    throw std::runtime_error(message);
}

// Control SQL and policy inspection deliberately use the C API in both builds.
// Timed row operations and owned verification use the selected statement API.
struct Db {
#ifdef USE_SQLITECPP
  std::unique_ptr<SQLite::Database> value;
#endif
  sqlite3 *p = nullptr;
  explicit Db(const char *path) {
    constexpr int flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                          SQLITE_OPEN_NOMUTEX | SQLITE_OPEN_PRIVATECACHE;
#ifdef USE_SQLITECPP
    value = std::make_unique<SQLite::Database>(path, flags);
    p = value->getHandle();
#else
    int rc = sqlite3_open_v2(path, &p, flags, nullptr);
    if (rc != SQLITE_OK) {
      if (p)
        sqlite3_close(p);
      p = nullptr;
      throw std::runtime_error("database open failed");
    }
#endif
  }
  Db(const Db &) = delete;
  Db &operator=(const Db &) = delete;
  ~Db() {
#ifndef USE_SQLITECPP
    if (p)
      sqlite3_close_v2(p); // Error-path cleanup; success uses checked close().
#endif
  }
  int control(const char *sql) {
    return sqlite3_exec(p, sql, nullptr, nullptr, nullptr);
  }
  void exec(const char *sql) {
    require(control(sql) == SQLITE_OK, "control SQL failed");
  }
  void close() {
    require(p && sqlite3_next_stmt(p, nullptr) == nullptr,
            "live statement at connection close");
#ifdef USE_SQLITECPP
    // SQLiteCpp destructors do not expose close/finalization status.
    value.reset();
#else
    require(sqlite3_close(p) == SQLITE_OK, "connection close failed");
#endif
    p = nullptr;
  }
};

struct Stmt {
#ifdef USE_SQLITECPP
  std::unique_ptr<SQLite::Statement> s;
  Stmt(Db &db, const char *sql)
      : s(std::make_unique<SQLite::Statement>(*db.value, sql)) {}
  void bind(int64_t id, const std::string &payload) {
    s->bind(1, id);
    s->bind(2, payload.data(), static_cast<int>(payload.size()));
  }
  bool step() { return s->executeStep(); }
  void reset() { s->reset(); }
  int64_t integer(int column) {
    auto value = s->getColumn(column);
    require(value.getType() == SQLITE_INTEGER, "noninteger ID");
    return value.getInt64();
  }
  void blob(int column, std::string &out) {
    auto value = s->getColumn(column);
    require(value.getType() == SQLITE_BLOB, "nonblob payload");
    const void *data = value.getBlob();
    int length = value.getBytes();
    require(length >= 0 && (data || length == 0), "invalid BLOB output");
    out.assign(length ? static_cast<const char *>(data) : "", length);
  }
  void finish() { s.reset(); }
#else
  sqlite3_stmt *s = nullptr;
  Stmt(Db &db, const char *sql) {
    int rc = sqlite3_prepare_v3(db.p, sql, -1, SQLITE_PREPARE_PERSISTENT, &s,
                                nullptr);
    if (rc != SQLITE_OK) {
      sqlite3_finalize(s);
      s = nullptr;
      throw std::runtime_error("statement prepare failed");
    }
  }
  ~Stmt() {
    if (s)
      sqlite3_finalize(s);
  }
  void bind(int64_t id, const std::string &payload) {
    require(sqlite3_bind_int64(s, 1, id) == SQLITE_OK, "ID binding failed");
    require(sqlite3_bind_blob(s, 2, payload.data(),
                              static_cast<int>(payload.size()),
                              SQLITE_TRANSIENT) == SQLITE_OK,
            "BLOB binding failed");
  }
  bool step() {
    int rc = sqlite3_step(s);
    require(rc == SQLITE_ROW || rc == SQLITE_DONE, "statement step failed");
    return rc == SQLITE_ROW;
  }
  void reset() {
    require(sqlite3_reset(s) == SQLITE_OK, "statement reset failed");
  }
  int64_t integer(int column) {
    require(sqlite3_column_type(s, column) == SQLITE_INTEGER, "noninteger ID");
    return sqlite3_column_int64(s, column);
  }
  void blob(int column, std::string &out) {
    require(sqlite3_column_type(s, column) == SQLITE_BLOB, "nonblob payload");
    const void *data = sqlite3_column_blob(s, column);
    int length = sqlite3_column_bytes(s, column);
    require(length >= 0 && (data || length == 0), "invalid BLOB output");
    out.assign(length ? static_cast<const char *>(data) : "", length);
  }
  void finish() {
    sqlite3_stmt *done = s;
    s = nullptr;
    require(sqlite3_finalize(done) == SQLITE_OK, "statement finalize failed");
  }
#endif
  Stmt(const Stmt &) = delete;
  Stmt &operator=(const Stmt &) = delete;
};

static std::string pragma(Db &db, const char *sql, bool integer) {
  sqlite3_stmt *s = nullptr;
  require(sqlite3_prepare_v2(db.p, sql, -1, &s, nullptr) == SQLITE_OK,
          "policy prepare failed");
  std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> cleanup(
      s, sqlite3_finalize);
  require(sqlite3_step(s) == SQLITE_ROW, "missing policy row");
  std::string value;
  if (integer) {
    require(sqlite3_column_type(s, 0) == SQLITE_INTEGER, "noninteger policy");
    value = std::to_string(sqlite3_column_int64(s, 0));
  } else {
    require(sqlite3_column_type(s, 0) == SQLITE_TEXT, "nontext policy");
    const unsigned char *text = sqlite3_column_text(s, 0);
    require(text != nullptr, "policy text allocation failed");
    value.assign(reinterpret_cast<const char *>(text),
                 sqlite3_column_bytes(s, 0));
  }
  require(sqlite3_step(s) == SQLITE_DONE, "extra policy row");
  require(sqlite3_finalize(cleanup.release()) == SQLITE_OK,
          "policy finalize failed");
  return value;
}

static std::string configure(Db &db) {
  require(sqlite3_extended_result_codes(db.p, 1) == SQLITE_OK, "extended codes failed");
  require(sqlite3_busy_timeout(db.p, 0) == SQLITE_OK, "busy timeout failed");
  db.exec("PRAGMA synchronous=FULL");
  db.exec("PRAGMA cache_size=-2000");
  db.exec("PRAGMA wal_autocheckpoint=1000");
  db.exec("PRAGMA foreign_keys=ON");
  db.exec("PRAGMA trusted_schema=OFF");
  db.exec("PRAGMA locking_mode=NORMAL");
  const std::string journal = pragma(db, "PRAGMA journal_mode", false);
  require(journal == "delete" || journal == "wal", "unsupported journal");
  const char *queries[] = {"PRAGMA synchronous",  "PRAGMA page_size",
                           "PRAGMA cache_size",   "PRAGMA wal_autocheckpoint",
                           "PRAGMA foreign_keys", "PRAGMA trusted_schema"};
  const char *expected[] = {"2", "4096", "-2000", "1000", "1", "0"};
  std::string policy = "policy " + journal;
  for (size_t i = 0; i < 6; ++i) {
    std::string actual = pragma(db, queries[i], true);
    require(actual == expected[i], "unexpected connection policy");
    policy += " " + actual;
  }
  const std::string locking = pragma(db, "PRAGMA locking_mode", false);
  const std::string busy = pragma(db, "PRAGMA busy_timeout", true);
  require(locking == "normal" && busy == "0", "unexpected locking policy");
  return policy + " " + locking + " " + busy;
}

static int64_t number(const char *text) {
  const std::string value(text);
  int64_t result = 0;
  const auto parsed =
      std::from_chars(value.data(), value.data() + value.size(), result);
  require(parsed.ec == std::errc() && parsed.ptr == value.data() + value.size(),
          "invalid number");
  return result;
}

using Clock = std::chrono::steady_clock;
static int64_t nanoseconds(Clock::time_point start) {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() -
                                                              start)
      .count();
}

int main(int argc, char **argv) {
  try {
    require(argc == 5, "expected PATH MODE TRANSACTIONS BATCH");
    const std::string mode(argv[2]);
    require(mode == "commit" || mode == "rollback" || mode == "busy",
            "invalid workload");
    const int64_t n = number(argv[3]), batch = number(argv[4]);
    require(n > 0 && n <= 10000 && batch > 0 && batch <= 1024 &&
                n * batch <= 1000000,
            "invalid workload bounds");
    std::string payload(128, 'x');
    payload[0] = 0;
    payload[127] = static_cast<char>(255);
    std::vector<int64_t> latencies(static_cast<size_t>(n));
    std::vector<int> codes(static_cast<size_t>(n), SQLITE_OK);
    Db db(argv[1]);
    const std::string policy = configure(db);
    Stmt insert(db, "INSERT INTO items VALUES(?1,?2)");
    auto put = [&](int64_t id) {
      insert.bind(id, payload);
      require(!insert.step(), "INSERT returned rows");
      insert.reset();
      require(sqlite3_changes64(db.p) == 1,
              "INSERT did not change exactly one row");
    };
    db.exec("BEGIN IMMEDIATE");
    put(-2);
    db.exec("ROLLBACK");
    db.exec("BEGIN IMMEDIATE");
    db.exec("COMMIT");
    db.exec("BEGIN IMMEDIATE");
    db.exec("ROLLBACK");
    std::unique_ptr<Db> blocker;
    if (mode == "busy") {
      blocker = std::make_unique<Db>(argv[1]);
      require(configure(*blocker) == policy, "blocker policy differs");
      blocker->exec("BEGIN IMMEDIATE");
      blocker->exec("UPDATE items SET payload=zeroblob(128) WHERE id=-1");
      require(sqlite3_changes64(blocker->p) == 1,
              "blocker changed wrong row count");
    }
    int64_t elapsed;
    if (blocker) {
      const auto loop_start = Clock::now();
      for (int64_t t = 0; t < n; ++t) {
        const auto start = Clock::now();
        const int code = db.control("BEGIN IMMEDIATE");
        require((code & 255) == SQLITE_BUSY, "BEGIN did not return BUSY");
        require(sqlite3_get_autocommit(db.p) != 0,
                "BUSY unexpectedly entered transaction");
        latencies[static_cast<size_t>(t)] = nanoseconds(start);
        codes[static_cast<size_t>(t)] = code;
      }
      elapsed = nanoseconds(loop_start);
    } else {
      const char *finish = mode == "commit" ? "COMMIT" : "ROLLBACK";
      const auto loop_start = Clock::now();
      for (int64_t t = 0; t < n; ++t) {
        const auto start = Clock::now();
        db.exec("BEGIN IMMEDIATE");
        for (int64_t i = 0; i < batch; ++i)
          put(t * batch + i);
        db.exec(finish);
        latencies[static_cast<size_t>(t)] = nanoseconds(start);
      }
      elapsed = nanoseconds(loop_start);
    }
    require(elapsed > 0, "invalid elapsed time");
    for (const auto latency : latencies)
      require(latency > 0, "invalid transaction latency");
    if (blocker) {
      blocker->exec("ROLLBACK");
      blocker->close();
      blocker.reset();
      db.exec("BEGIN IMMEDIATE");
      put(0);
      db.exec("COMMIT");
    }
    insert.finish();
    const int64_t rows = mode == "commit" ? n * batch : mode == "busy" ? 1 : 0;
    int64_t checksum = 0;
    std::string out;
    out.reserve(payload.size());
    Stmt query(db, "SELECT id,payload FROM items ORDER BY id");
    for (int64_t row = -1; row < rows; ++row) {
      require(query.step(), "missing stored row");
      const int64_t id = query.integer(0);
      require(id == row, "unexpected stored ID");
      query.blob(1, out);
      require(out == payload, "stored BLOB differs");
      checksum += id + 2;
    }
    require(!query.step(), "extra stored row");
    query.finish();
    require(checksum == 1 + rows * (rows + 3) / 2, "checksum differs");
    require(sqlite3_get_autocommit(db.p) != 0, "transaction left active");
    db.close();
    // Output is delayed until all verification and connection cleanup
    // succeeded.
    std::puts(policy.c_str());
    std::printf("%lld %lld %lld %lld %lld\n", static_cast<long long>(elapsed),
                static_cast<long long>(checksum),
                static_cast<long long>(mode == "commit" ? n : 0),
                static_cast<long long>(mode == "busy" ? n : 0),
                static_cast<long long>(mode == "rollback" ? n : 0));
    for (size_t i = 0; i < latencies.size(); ++i)
      std::printf("%lld %d\n", static_cast<long long>(latencies[i]), codes[i]);
    return 0;
  } catch (const std::exception &error) {
    std::fprintf(stderr, "file-backed runner failed: %s\n", error.what());
    return 1;
  }
}
