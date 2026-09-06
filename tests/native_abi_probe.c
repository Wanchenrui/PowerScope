/* Compiled against the production headers; compared with ctypes in pytest. */
#include <stdio.h>
#include <stddef.h>
#include "modbus_codec.h"
#include "debug_protocol.h"
#define SIZE(type) printf("%s.size=%zu\n", #type, sizeof(type))
#define FIELD(type, field) printf("%s.%s=%zu\n", #type, #field, offsetof(type, field))
int main(void) {
    SIZE(modbus_request_t);
    FIELD(modbus_request_t, start_addr);
    FIELD(modbus_request_t, write_value);
    SIZE(modbus_response_t);
    FIELD(modbus_response_t, registers);
    FIELD(modbus_response_t, reg_count);
    FIELD(modbus_response_t, written_addr);
    FIELD(modbus_response_t, is_exception);
    SIZE(dbg_frame_t);
    FIELD(dbg_frame_t, seq);
    FIELD(dbg_frame_t, address);
    FIELD(dbg_frame_t, payload);
    FIELD(dbg_frame_t, payload_len);
    printf("pointer.size=%zu\n", sizeof(void *));
    return 0;
}
