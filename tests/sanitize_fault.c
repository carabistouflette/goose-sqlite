// SPDX-License-Identifier: Apache-2.0
/* A deliberately undersized heap buffer for the sanitizer negative control.
   tests/sanitize_fault.goose reads past it through ffi::bytes, which trusts
   the pointer and length it is given, so no Goose bounds check stands between
   the fault and the sanitizer. */
#include <stdlib.h>

void *gs_test_undersized_buffer(void) {
    unsigned char *buffer = malloc(16);
    if (buffer == NULL) return NULL;
    for (int i = 0; i < 16; i++) buffer[i] = (unsigned char)i;
    return buffer;
}
