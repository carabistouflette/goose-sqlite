// SPDX-License-Identifier: Apache-2.0
// Runtime sensitivity control: the invalid FFI copy must be caught by ASan.
// This alone can fire through an interceptor in a link-only build, so the
// sanitize gate separately verifies instrumentation of the generated object.
import ffi;

extern fn undersized_buffer() -> u64 = "gs_test_undersized_buffer";

fn main() {
    let pointer = undersized_buffer();
    assert(pointer != 0);
    var out: u8[>..] = [];
    assert(ffi::bytes(pointer, 64, out));
    assert(out.len == 64);
}
