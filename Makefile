GOOSE ?= .toolchain/goose/build/goose
CC ?= cc
PUBLIC_TEST_DIR ?= .build
FUZZ_CC ?= clang
FUZZ_RUNS ?= 10000
BENCH_ITERATIONS ?= 10000
.PHONY: setup format check test test-import test-native fuzz-native bench
setup:
	./scripts/setup-goose.sh
format:
	python3 scripts/native-manifest.py
	"$(GOOSE)" format sqlite.goose examples tests bench
check:
	python3 scripts/native-manifest.py --check
	"$(GOOSE)" format --check sqlite.goose examples tests bench
	"$(GOOSE)" check tests/api.goose
	"$(GOOSE)" check tests/diagnostics.goose
	"$(GOOSE)" check tests/storage.goose
	"$(GOOSE)" check tests/metadata.goose
	"$(GOOSE)" check tests/files.goose
	"$(GOOSE)" check examples/transactions.goose
	"$(GOOSE)" check examples/items.goose
	"$(GOOSE)" check bench/storage/runner.goose
	"$(GOOSE)" check bench/bench.goose
	"$(GOOSE)" check bench/alternatives/runner.goose
test:
	python3 scripts/native-manifest.py --check
	"$(GOOSE)" run tests/api.goose
	"$(GOOSE)" run tests/diagnostics.goose
	"$(GOOSE)" run tests/storage.goose
	"$(GOOSE)" run tests/metadata.goose
	mkdir -p "$(PUBLIC_TEST_DIR)"
	"$(GOOSE)" build tests/api.goose -o "$(PUBLIC_TEST_DIR)/api"
	"$(PUBLIC_TEST_DIR)/api"
	"$(GOOSE)" build tests/metadata.goose -o "$(PUBLIC_TEST_DIR)/metadata"
	"$(PUBLIC_TEST_DIR)/metadata"
	"$(GOOSE)" build tests/storage.goose -o "$(PUBLIC_TEST_DIR)/storage"
	"$(PUBLIC_TEST_DIR)/storage"
	"$(GOOSE)" build tests/diagnostics.goose -o "$(PUBLIC_TEST_DIR)/diagnostics"
	"$(PUBLIC_TEST_DIR)/diagnostics"
	python3 scripts/test-files.py "$(GOOSE)"
	"$(GOOSE)" run examples/transactions.goose
	"$(GOOSE)" build examples/transactions.goose -o "$(PUBLIC_TEST_DIR)/transactions"
	"$(PUBLIC_TEST_DIR)/transactions"
	"$(GOOSE)" run examples/items.goose
	$(MAKE) test-import
test-import:
	python3 scripts/test-import.py --goose "$(GOOSE)"
test-native:
	cmake -S . -B .build/native-$(notdir $(CC)) -DCMAKE_C_COMPILER="$(CC)" -DCMAKE_BUILD_TYPE=Debug -DGOOSE_SQLITE_NATIVE_TESTS=ON
	cmake --build .build/native-$(notdir $(CC)) --parallel 2
	UBSAN_OPTIONS=halt_on_error=1 .build/native-$(notdir $(CC))/goose_sqlite_test
	UBSAN_OPTIONS=halt_on_error=1 .build/native-$(notdir $(CC))/goose_sqlite_fault_test
	UBSAN_OPTIONS=halt_on_error=1 .build/native-$(notdir $(CC))/goose_sqlite_storage_test
	python3 scripts/test-threads.py --binary .build/native-$(notdir $(CC))/goose_sqlite_thread_test --output .build/threads-$(notdir $(CC)).json
	python3 scripts/test-recovery.py --binary .build/native-$(notdir $(CC))/goose_sqlite_recovery_test --output .build/recovery-$(notdir $(CC)).json
fuzz-native:
	cmake -S . -B .build/fuzz -DCMAKE_C_COMPILER="$(FUZZ_CC)" -DCMAKE_BUILD_TYPE=Debug -DGOOSE_SQLITE_FUZZ=ON
	cmake --build .build/fuzz --parallel 2
	mkdir -p .build/corpus .build/artifacts
	cp tests/corpus/* .build/corpus/
	UBSAN_OPTIONS=halt_on_error=1 .build/fuzz/goose_sqlite_fuzz .build/corpus -artifact_prefix=.build/artifacts/ -dict=tests/fuzz.dict -seed=219 -max_len=4096 -runs=$(FUZZ_RUNS)
bench:
	python3 bench/measure.py --goose "$(GOOSE)" --iterations $(BENCH_ITERATIONS) --output .build/bench-results

.PHONY: bench-alternatives
bench-alternatives:
	python3 bench/alternatives/measure.py --goose "$(GOOSE)" --iterations $(BENCH_ITERATIONS) --output .build/alternative-results
