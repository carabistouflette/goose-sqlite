// SPDX-License-Identifier: Apache-2.0
#include "../filebacked/paths.hpp"
#include <iostream>
#include <utility>

using Payloads = std::vector<std::vector<std::string>>;

static std::string command() {
  char buffer[16];
  std::cin.getline(buffer, sizeof buffer);
  require(std::cin.good(), "missing, overlong or unterminated command");
  return std::string(buffer, static_cast<size_t>(std::cin.gcount() - 1));
}
static void emit(const std::string &line) {
  std::cout << line << '\n' << std::flush;
  require(std::cout.good(), "protocol output failed");
}
static void control(Db &db, const char *sql, const char *stage) {
  const int code = db.control(sql);
  if (code != SQLITE_OK)
    throw std::runtime_error(std::string(stage) + " SQLite code=" + std::to_string(code));
}
static Payloads payloads(int64_t attempts, int64_t rows) {
  Payloads values(static_cast<size_t>(attempts + 1));
  for (int64_t epoch = 0; epoch <= attempts; ++epoch) {
    auto &generation = values[static_cast<size_t>(epoch)];
    generation.reserve(static_cast<size_t>(rows));
    for (int64_t id = 0; id < rows; ++id) {
      std::string value(128, '\0');
      for (int64_t j = 1; j < 127; ++j)
        value[static_cast<size_t>(j)] = static_cast<char>((epoch * 17 + id * 31 + j * 7) % 256);
      value[127] = static_cast<char>(255);
      generation.push_back(std::move(value));
    }
  }
  return values;
}
static void update(Db &db, Stmt &statement, const Payloads &values,
                   int64_t epoch, int64_t rows) {
  require(epoch >= 0 && static_cast<size_t>(epoch) < values.size(), "invalid update epoch");
  try {
    for (int64_t id = 0; id < rows; ++id) {
      statement.bind_integer(1, epoch);
      statement.bind_blob(2, values[static_cast<size_t>(epoch)][static_cast<size_t>(id)]);
      statement.bind_integer(3, id);
      require(!statement.step(), "UPDATE returned a row");
      statement.reset();
      require(sqlite3_changes64(db.p) == 1, "UPDATE changed wrong row count");
    }
  } catch (const std::exception &error) {
    throw std::runtime_error("UPDATE SQLite code=" + std::to_string(sqlite3_extended_errcode(db.p)) + " " + error.what());
  }
}
static int64_t snapshot(Db &db, Stmt &statement, const Payloads &values,
                        int64_t rows, std::string &owned) {
  int64_t epoch = -1;
  try {
    for (int64_t id = 0; id < rows; ++id) {
      require(statement.step(), "snapshot missing row");
      require(statement.integer(0) == id, "snapshot ID differs");
      const int64_t actual = statement.integer(1);
      require(actual >= 0 && static_cast<size_t>(actual) < values.size(), "snapshot epoch out of range");
      if (id == 0) epoch = actual;
      require(actual == epoch, "snapshot contains mixed epochs");
      statement.blob(2, owned);
      require(owned == values[static_cast<size_t>(actual)][static_cast<size_t>(id)], "snapshot payload differs");
    }
    require(!statement.step(), "snapshot has extra rows");
    statement.reset();
  } catch (const std::exception &error) {
    throw std::runtime_error("SELECT SQLite code=" + std::to_string(sqlite3_extended_errcode(db.p)) + " " + error.what());
  }
  return epoch;
}

int main(int argc, char **argv) {
  try {
    require(argc == 7, "expected PATH ROLE PHASE ATTEMPTS ROWS READ_CAP");
    const std::string role(argv[2]), phase(argv[3]);
    require(role == "reader" || role == "writer", "invalid role");
    require(phase == "qualify" || phase == "mixed", "invalid phase");
    const int64_t attempts = number(argv[4]), rows = number(argv[5]), cap = number(argv[6]);
    require(attempts >= 8 && attempts <= 4096 && rows >= 1 && rows <= 256 &&
                cap >= 1 && cap <= 100000 && (attempts + 1) * rows <= 32768,
            "invalid workload bounds");
    const Payloads values = payloads(attempts, rows);
    Db db(argv[1]);
    const std::string policy = configure(db);
    require(policy.rfind("policy wal ", 0) == 0, "mixed workload requires WAL");
    std::unique_ptr<Stmt> statement;
    std::string owned;
    owned.reserve(128);
    if (role == "writer") {
      statement = std::make_unique<Stmt>(db, "UPDATE items SET epoch=?1,payload=?2 WHERE id=?3");
      control(db, "BEGIN IMMEDIATE", "prime BEGIN");
      update(db, *statement, values, 0, rows);
      control(db, "ROLLBACK", "prime ROLLBACK");
      control(db, "BEGIN IMMEDIATE", "prime empty BEGIN");
      control(db, "COMMIT", "prime empty COMMIT");
      control(db, "BEGIN IMMEDIATE", "prime empty BEGIN");
      control(db, "ROLLBACK", "prime empty ROLLBACK");
    } else {
      statement = std::make_unique<Stmt>(db, "SELECT id,epoch,payload FROM items ORDER BY id");
      control(db, "BEGIN DEFERRED", "prime BEGIN");
      require(snapshot(db, *statement, values, rows, owned) == 0, "prime epoch differs");
      control(db, "COMMIT", "prime COMMIT");
    }
    require(sqlite3_get_autocommit(db.p) != 0, "priming left transaction active");
    emit(policy);
    emit("READY " + role);
    if (phase == "qualify") {
      int step = 0;
      bool held = false;
      for (;;) {
        const std::string input = command();
        if (input == "S") {
          require(!held && step == (role == "writer" ? 3 : 5), "premature qualification stop");
          break;
        }
        if (role == "writer") {
          if (input == "C" && step == 0) {
            control(db, "BEGIN IMMEDIATE", "qualify BEGIN");
            update(db, *statement, values, 1, rows);
            control(db, "COMMIT", "qualify COMMIT");
            ++step; emit("COMMITTED 1");
          } else if (input == "U" && step == 1) {
            control(db, "BEGIN IMMEDIATE", "qualify dirty BEGIN");
            update(db, *statement, values, 2, rows);
            held = true; ++step; emit("DIRTY 2");
          } else if (input == "B" && step == 2 && held) {
            control(db, "ROLLBACK", "qualify ROLLBACK");
            held = false; ++step; emit("ROLLED_BACK 2");
          } else throw std::runtime_error("unexpected writer qualification command");
        } else {
          if (input == "H" && step == 0) {
            control(db, "BEGIN DEFERRED", "qualify held BEGIN");
            require(snapshot(db, *statement, values, rows, owned) == 0, "held epoch differs");
            held = true; ++step; emit("HELD 0");
          } else if (input == "V" && step == 1 && held) {
            require(snapshot(db, *statement, values, rows, owned) == 0, "held snapshot changed");
            ++step; emit("VERIFIED 0");
          } else if (input == "F" && step >= 2 && step <= 4) {
            if (held) { control(db, "COMMIT", "qualify release"); held = false; }
            control(db, "BEGIN DEFERRED", "qualify fresh BEGIN");
            require(snapshot(db, *statement, values, rows, owned) == 1, "fresh epoch differs");
            control(db, "COMMIT", "qualify fresh COMMIT");
            ++step; emit("FRESH 1");
          } else throw std::runtime_error("unexpected reader qualification command");
        }
      }
    } else {
      require(command() == "G", "missing start command");
      emit("START " + role);
      const auto window = Clock::now();
      int64_t successes = 0, busy = 0;
      if (role == "writer") {
        for (int64_t index = 1; index <= attempts; ++index) {
          const auto operation = Clock::now();
          const int code = db.control("BEGIN IMMEDIATE");
          if (code == SQLITE_OK) {
            update(db, *statement, values, successes + 1, rows);
            control(db, "COMMIT", "mixed COMMIT");
            ++successes;
          } else {
            if ((code & 255) != SQLITE_BUSY)
              throw std::runtime_error("writer BEGIN SQLite code=" + std::to_string(code));
            require(sqlite3_get_autocommit(db.p) != 0, "writer BUSY entered transaction");
            ++busy;
          }
          const int64_t elapsed = nanoseconds(operation);
          require(elapsed > 0, "invalid writer latency");
          emit("W " + std::to_string(index) + " " + std::to_string(elapsed) + " " +
               std::to_string(code) + " " + std::to_string(successes));
        }
      } else {
        int64_t prior = 0;
        for (int64_t index = 1;; ++index) {
          require(index <= cap, "reader cap reached");
          const auto operation = Clock::now();
          const int code = db.control("BEGIN DEFERRED");
          int64_t epoch = -1;
          if (code == SQLITE_OK) {
            epoch = snapshot(db, *statement, values, rows, owned);
            require(epoch >= prior, "reader epoch decreased");
            control(db, "COMMIT", "mixed reader COMMIT");
            prior = epoch; ++successes;
          } else {
            if ((code & 255) != SQLITE_BUSY)
              throw std::runtime_error("reader BEGIN SQLite code=" + std::to_string(code));
            require(sqlite3_get_autocommit(db.p) != 0, "reader BUSY entered transaction");
            ++busy;
          }
          const int64_t elapsed = nanoseconds(operation);
          require(elapsed > 0, "invalid reader latency");
          emit("R " + std::to_string(index) + " " + std::to_string(elapsed) + " " +
               std::to_string(code) + " " + std::to_string(epoch));
          const std::string input = command();
          if (input == "S") break;
          require(input == "N", "unexpected reader continuation command");
        }
      }
      const int64_t elapsed = nanoseconds(window);
      require(elapsed > 0, "invalid role window");
      emit("DONE " + role + " " + std::to_string(elapsed) + " " +
           std::to_string(successes) + " " + std::to_string(busy));
    }
    require(sqlite3_get_autocommit(db.p) != 0, "role left transaction active");
    statement->finish();
    statement.reset();
    db.close();
    emit("END " + role);
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "mixed WAL runner failed: " << error.what() << '\n';
    return 1;
  }
}
