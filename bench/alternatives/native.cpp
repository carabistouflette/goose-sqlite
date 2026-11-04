// SPDX-License-Identifier: Apache-2.0
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <sqlite3.h>
#include <string>
#ifdef USE_SQLITECPP
#include <SQLiteCpp/SQLiteCpp.h>
#endif
static void require(bool x) {
  if (!x)
    std::abort();
}
struct Db {
#ifdef USE_SQLITECPP
  SQLite::Database value{":memory:",
                         SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                             SQLITE_OPEN_NOMUTEX | SQLITE_OPEN_PRIVATECACHE};
  sqlite3 *p = value.getHandle();
#else
  sqlite3 *p = nullptr;
  Db() {
    require(sqlite3_open_v2(":memory:", &p,
                            SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE |
                                SQLITE_OPEN_NOMUTEX | SQLITE_OPEN_PRIVATECACHE,
                            nullptr) == SQLITE_OK);
  }
  ~Db() { require(sqlite3_close(p) == SQLITE_OK); }
#endif
  void exec(const char *sql) {
    require(sqlite3_exec(p, sql, nullptr, nullptr, nullptr) == SQLITE_OK);
  }
};
struct Stmt {
#ifdef USE_SQLITECPP
  SQLite::Statement s;
  Stmt(Db &d, const char *sql) : s(d.value, sql) {}
  void integer(int64_t x, int index = 1) { s.bind(index, x); }
  void bytes(const std::string &x, bool blob, int index = 1) {
    if (blob)
      s.bind(index, x.data(), static_cast<int>(x.size()));
    else
      s.bind(index, x);
  }
  bool step() { return s.executeStep(); }
  int64_t integer(int column = 0) { return s.getColumn(column).getInt64(); }
  std::string bytes() { return s.getColumn(0).getString(); }
  void reset() { s.reset(); }
#else
  sqlite3_stmt *s = nullptr;
  Stmt(Db &d, const char *sql) {
    require(sqlite3_prepare_v3(d.p, sql, -1, SQLITE_PREPARE_PERSISTENT, &s,
                               nullptr) == SQLITE_OK);
  }
  ~Stmt() { require(sqlite3_finalize(s) == SQLITE_OK); }
  void integer(int64_t x, int index = 1) {
    require(sqlite3_bind_int64(s, index, x) == SQLITE_OK);
  }
  void bytes(const std::string &x, bool blob, int index = 1) {
    require(
        (blob
             ? sqlite3_bind_blob(s, index, x.data(), static_cast<int>(x.size()),
                                 SQLITE_TRANSIENT)
             : sqlite3_bind_text(s, index, x.data(), static_cast<int>(x.size()),
                                 SQLITE_TRANSIENT)) == SQLITE_OK);
  }
  bool step() {
    int rc = sqlite3_step(s);
    require(rc == SQLITE_ROW || rc == SQLITE_DONE);
    return rc == SQLITE_ROW;
  }
  int64_t integer(int column = 0) {
    require(sqlite3_column_type(s, column) == SQLITE_INTEGER);
    return sqlite3_column_int64(s, column);
  }
  std::string bytes() {
    const void *p = sqlite3_column_blob(s, 0);
    int n = sqlite3_column_bytes(s, 0);
    require(p || !n);
    return n ? std::string(static_cast<const char *>(p), n) : std::string();
  }
  void reset() { require(sqlite3_reset(s) == SQLITE_OK); }
#endif
  void copy_blob(int column, std::string &out) {
#ifdef USE_SQLITECPP
    auto c = s.getColumn(column);
    require(c.getType() == SQLITE_BLOB);
    const void *p = c.getBlob();
    int n = c.getBytes();
#else
    require(sqlite3_column_type(s, column) == SQLITE_BLOB);
    const void *p = sqlite3_column_blob(s, column);
    int n = sqlite3_column_bytes(s, column);
#endif
    require(p || !n);
    out.assign(n ? static_cast<const char *>(p) : "", n);
  }
};
int main(int argc, char **argv) {
  if (argc == 2 && std::string(argv[1]) == "identity") {
    printf("%s\n%s\n", sqlite3_libversion(), sqlite3_sourceid());
    for (int i = 0; sqlite3_compileoption_get(i); ++i)
      puts(sqlite3_compileoption_get(i));
    return 0;
  }
  require(argc == 4);
  int64_t n = std::stoll(argv[1]);
  std::string mode = argv[2];
  int size = std::stoi(argv[3]);
  require(n > 0 && n <= 10000000 && size >= 0 && size <= 65536);
  Db db;
  require(sqlite3_busy_timeout(db.p, 1000) == SQLITE_OK);
  int64_t checksum = 0, elapsed = 0;
  auto now = []() { return std::chrono::steady_clock::now(); };
  auto duration = [&](auto start) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(now() - start)
        .count();
  };
  if (mode == "prepare") {
    auto start = now();
    for (int64_t i = 0; i < n; ++i) {
      Stmt s(db, "SELECT 1");
      require(s.step());
      checksum += s.integer();
      require(!s.step());
    }
    elapsed = duration(start);
  } else if (mode == "scalar") {
    Stmt s(db, "SELECT ?1");
    auto start = now();
    for (int64_t i = 0; i < n; ++i) {
      s.integer(i);
      require(s.step());
      require(s.integer() == i);
      checksum += i;
      require(!s.step());
      s.reset();
    }
    elapsed = duration(start);
  } else if (mode == "text" || mode == "blob") {
    Stmt s(db, "SELECT ?1");
    std::string input(size, 'x');
    auto start = now();
    for (int64_t i = 0; i < n; ++i) {
      s.bytes(input, mode == "blob");
      require(s.step());
      auto out = s.bytes();
      require(out == input);
      checksum += out.size();
      require(!s.step());
      s.reset();
    }
    elapsed = duration(start);
  } else if (mode == "scan" || mode == "lookup" || mode == "batch") {
    require(size >= 2);
    std::string input(size, 'x');
    input.front() = 0;
    input.back() = static_cast<char>(255);
    std::string out;
    out.reserve(input.size());
    db.exec("CREATE TABLE items(id INTEGER PRIMARY KEY,group_id "
            "INTEGER,payload BLOB)");
    db.exec("CREATE INDEX by_group ON items(group_id)");
    if (mode != "batch") {
      db.exec("BEGIN");
      {
        Stmt insert(db, "INSERT INTO items VALUES(?1,?1%17,?2)");
        for (int64_t i = 0; i < 1024; ++i) {
          insert.integer(i);
          insert.bytes(input, true, 2);
          require(!insert.step());
          insert.reset();
        }
      }
      db.exec("COMMIT");
    }
    if (mode == "batch") {
      {
        Stmt insert(db, "INSERT INTO items VALUES(?1,?1%17,?2)");
        auto start = now();
        db.exec("BEGIN");
        for (int64_t i = 0; i < n; ++i) {
          insert.integer(i);
          insert.bytes(input, true, 2);
          require(!insert.step());
          insert.reset();
        }
        db.exec("COMMIT");
        elapsed = duration(start);
      }
      Stmt q(db, "SELECT id,group_id,payload FROM items ORDER BY id");
      for (int64_t i = 0; i < n; ++i) {
        require(q.step() && q.integer() == i && q.integer(1) == i % 17);
        q.copy_blob(2, out);
        require(out == input);
      }
      require(!q.step());
      checksum = n * size;
    } else if (mode == "scan") {
      Stmt q(db, "SELECT id,payload FROM items ORDER BY id");
      auto start = now();
      for (int64_t pass = 0; pass < n; ++pass) {
        for (int64_t i = 0; i < 1024; ++i) {
          require(q.step() && q.integer() == i);
          q.copy_blob(1, out);
          require(out == input);
          checksum += out.size();
        }
        require(!q.step());
        q.reset();
      }
      elapsed = duration(start);
    } else {
      Stmt q(db, "SELECT id,payload FROM items WHERE id=?1");
      auto start = now();
      for (int64_t i = 0; i < n; ++i) {
        int64_t id = (i * 17) % 1024;
        q.integer(id);
        require(q.step() && q.integer() == id);
        q.copy_blob(1, out);
        require(out == input);
        checksum += out.size();
        require(!q.step());
        q.reset();
      }
      elapsed = duration(start);
    }
  } else {
    require(mode == "insert");
    db.exec("CREATE TABLE items(x INTEGER)");
    {
      Stmt s(db, "INSERT INTO items VALUES(?1)");
      auto start = now();
      db.exec("BEGIN");
      for (int64_t i = 0; i < n; ++i) {
        s.integer(i);
        require(!s.step());
        s.reset();
      }
      db.exec("COMMIT");
      elapsed = duration(start);
    }
    Stmt q(db, "SELECT count(*), sum(x) FROM items");
    require(q.step());
    require(q.integer() == n && q.integer(1) == n * (n - 1) / 2);
    require(!q.step());
    checksum = n;
  }
  printf("%lld %lld\n", (long long)elapsed, (long long)checksum);
}
