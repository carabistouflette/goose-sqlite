/* SPDX-License-Identifier: Apache-2.0 */
#ifndef GOOSE_SQLITE_H
#define GOOSE_SQLITE_H
#include <stdint.h>
/* Internal ABI. Slices and scalar references may be byte-aligned. */
#pragma pack(push, 1)
typedef struct { const uint8_t *data; int64_t len; } gq_input;
typedef struct { uint8_t *data; int64_t len; } gq_output;
#pragma pack(pop)
enum { GQ_INPUT = -1, GQ_HANDLE = -2, GQ_STATE = -3, GQ_TYPE = -4, GQ_LIMIT = -5 };
int64_t gq_open(gq_input path, int64_t readonly, int64_t busy_ms, int64_t budget, void *token);
int64_t gq_close(uint64_t token);
int64_t gq_prepare(uint64_t db, gq_input sql, void *token);
int64_t gq_finalize(uint64_t token);
int64_t gq_reset(uint64_t token);
int64_t gq_clear(uint64_t token);
int64_t gq_bind(uint64_t token, int64_t index, int64_t kind, int64_t integer, double real, gq_input bytes);
int64_t gq_step(uint64_t token);
int64_t gq_columns(uint64_t token);
int64_t gq_type(uint64_t token, int64_t column);
int64_t gq_integer(uint64_t token, int64_t column, void *value);
int64_t gq_real(uint64_t token, int64_t column, void *value);
int64_t gq_size(uint64_t token, int64_t column, int64_t kind, void *size);
int64_t gq_copy(uint64_t token, int64_t column, int64_t kind, gq_output out);
int64_t gq_message(uint64_t token, gq_output out);
int64_t gq_parameter_count(uint64_t token);
int64_t gq_parameter_index(uint64_t token, gq_input name);
int64_t gq_name(uint64_t token, int64_t column, gq_output out, void *length);
int64_t gq_status(uint64_t token, int64_t kind, void *out);
#endif
