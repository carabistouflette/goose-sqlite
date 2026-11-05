// SPDX-License-Identifier: Apache-2.0
#include "paths.hpp"

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
