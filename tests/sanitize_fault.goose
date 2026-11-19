// SPDX-License-Identifier: Apache-2.0
// Negative control for `make sanitize`. ffi::bytes trusts the pointer and
// length it is given, so this reads 64 bytes from a 16-byte heap buffer with
// no Goose bounds check in the way: only the sanitizer can stop it. The
// control is sensitive because the same fault is silent without ASan.
import ffi;

extern fn undersized_buffer() -> u64 = "gs_test_undersized_buffer";

fn main() {
    let pointer = undersized_buffer();
    assert(pointer != 0);
    var out: u8[>..] = [];
    assert(ffi::bytes(pointer, 64, out));
    assert(out.len == 64);
}
