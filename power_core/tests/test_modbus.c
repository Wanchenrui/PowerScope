/**
 * test_modbus.c — Modbus RTU 帧编解码单元测试
 *
 * 测试策略:
 * 1. 构建请求帧 + 验证帧内容 + CRC
 * 2. 构建响应帧 → 解析 → 验证字段一致
 * 3. 异常响应解析
 * 4. CRC 错误检测
 * 5. 从站/功能码不匹配检测
 * 6. 帧长度期望判断
 * 7. 写多寄存器
 */
#include "../include/modbus_codec.h"
#include "../include/crc16_table.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>

static int tests_run = 0;
static int tests_pass = 0;

#define TEST(name) do { tests_run++; printf("  [TEST] %s ... ", name); } while(0)
#define PASS() do { tests_pass++; printf("PASS\n"); } while(0)
#define FAIL(msg) do { printf("FAIL: %s\n", msg); return; } while(0)

void test_build_read_holding(void) {
    TEST("build_read_holding_request");
    uint8_t buf[32];
    int32_t len = modbus_build_read_holding(buf, sizeof(buf), 0x01, 0x0000, 0x000A);
    if (len != 8) FAIL("expected len=8");
    /* 帧内容: 01 03 00 00 00 0A CRC_lo CRC_hi */
    if (buf[0] != 0x01) FAIL("slave_id");
    if (buf[1] != 0x03) FAIL("fc");
    if (buf[2] != 0x00 || buf[3] != 0x00) FAIL("start_addr");
    if (buf[4] != 0x00 || buf[5] != 0x0A) FAIL("reg_count");
    /* CRC = 0xCDC5 → 小端 C5 CD */
    if (buf[6] != 0xC5 || buf[7] != 0xCD) {
        char msg[64]; sprintf(msg, "CRC: got %02X %02X, expected C5 CD", buf[6], buf[7]);
        FAIL(msg);
    }
    PASS();
}

void test_parse_read_response(void) {
    TEST("parse_read_holding_response");
    /* 构建响应: slave=1, fc=03, 读2个寄存器, 值=0x1234 0x5678 */
    uint16_t regs[] = {0x1234, 0x5678};
    uint8_t buf[32];
    int32_t len = modbus_build_read_holding_response(buf, sizeof(buf), 0x01, regs, 2);
    if (len < 0) FAIL("build response failed");

    modbus_request_t req = {.slave_id=1, .function_code=3, .start_addr=0, .reg_count=2};
    modbus_response_t resp;
    int32_t rc = modbus_parse_rtu_response(buf, len, &req, &resp);
    if (rc != MB_OK) FAIL("parse failed");
    if (resp.slave_id != 1) FAIL("slave_id");
    if (resp.function_code != 3) FAIL("fc");
    if (resp.reg_count != 2) FAIL("reg_count");
    if (resp.registers[0] != 0x1234) FAIL("reg[0]");
    if (resp.registers[1] != 0x5678) FAIL("reg[1]");
    PASS();
}

void test_exception_response(void) {
    TEST("parse_exception_response");
    /* 异常响应: slave=1, fc=0x83, exc=0x02 (非法地址) */
    uint8_t buf[32];
    buf[0] = 0x01; buf[1] = 0x83; buf[2] = 0x02;
    uint16_t crc = crc16_modbus(buf, 3);
    buf[3] = crc & 0xFF; buf[4] = crc >> 8;

    modbus_response_t resp;
    int32_t rc = modbus_parse_rtu_response(buf, 5, NULL, &resp);
    if (rc != MB_ERR_EXCEPT) FAIL("expected MB_ERR_EXCEPT");
    if (!resp.is_exception) FAIL("not exception");
    if (resp.exception_code != 0x02) FAIL("exc code");
    PASS();
}

void test_crc_error_detection(void) {
    TEST("crc_error_detection");
    uint8_t buf[32];
    int32_t len = modbus_build_read_holding(buf, sizeof(buf), 0x01, 0x0000, 0x000A);
    if (len < 0) FAIL("build failed");
    /* 破坏一个字节 */
    buf[2] ^= 0xFF;
    modbus_response_t resp;
    int32_t rc = modbus_parse_rtu_response(buf, len, NULL, &resp);
    if (rc != MB_ERR_CRC) FAIL("expected MB_ERR_CRC");
    PASS();
}

void test_slave_mismatch(void) {
    TEST("slave_id_mismatch");
    uint16_t regs[] = {0x0001};
    uint8_t buf[32];
    int32_t len = modbus_build_read_holding_response(buf, sizeof(buf), 0x02, regs, 1);
    modbus_request_t req = {.slave_id=1, .function_code=3, .reg_count=1};
    modbus_response_t resp;
    int32_t rc = modbus_parse_rtu_response(buf, len, &req, &resp);
    if (rc != MB_ERR_ADDR) FAIL("expected MB_ERR_ADDR");
    PASS();
}

void test_write_single(void) {
    TEST("write_single_register");
    uint8_t buf[32];
    int32_t len = modbus_build_write_single(buf, sizeof(buf), 0x01, 0x006B, 0x012C);
    if (len != 8) FAIL("len != 8");
    /* 01 06 00 6B 01 2C CRC */
    if (buf[0] != 0x01) FAIL("slave");
    if (buf[1] != 0x06) FAIL("fc");
    if (buf[2] != 0x00 || buf[3] != 0x6B) FAIL("addr");
    if (buf[4] != 0x01 || buf[5] != 0x2C) FAIL("value");
    /* 解析回写响应 (FC=06 响应=请求回显) */
    modbus_request_t req = {.slave_id=1, .function_code=6};
    modbus_response_t resp;
    int32_t rc = modbus_parse_rtu_response(buf, len, &req, &resp);
    if (rc != MB_OK) FAIL("parse failed");
    if (resp.written_addr != 0x006B) FAIL("written_addr");
    if (resp.written_count != 0x012C) FAIL("written_value");
    PASS();
}

void test_write_multi(void) {
    TEST("write_multi_registers");
    uint8_t buf[64];
    uint16_t regs[] = {0x000A, 0x0102, 0x0304};
    int32_t len = modbus_build_write_multi(buf, sizeof(buf), 0x01, 0x0001, regs, 3);
    if (len < 0) FAIL("build failed");
    /* 01 10 00 01 00 03 06 00 0A 01 02 03 04 CRC CRC = 15 字节 */
    if (len != 15) FAIL("expected 15 bytes");
    if (buf[6] != 6) FAIL("byte_count"); /* 3 regs * 2 = 6 bytes */
    /* 解析写多响应: slave+fc+addr(2)+count(2)+crc(2) = 8 */
    modbus_request_t req = {.slave_id=1, .function_code=0x10};
    modbus_response_t resp;
    /* 写多响应只有 8 字节 (回显 addr+count, 不含数据) */
    /* 模拟构建写多响应 */
    uint8_t resp_buf[32];
    resp_buf[0] = 0x01; resp_buf[1] = 0x10;
    resp_buf[2] = 0x00; resp_buf[3] = 0x01; /* addr */
    resp_buf[4] = 0x00; resp_buf[5] = 0x03; /* count */
    uint16_t crc = crc16_modbus(resp_buf, 6);
    resp_buf[6] = crc & 0xFF; resp_buf[7] = crc >> 8;
    int32_t rc = modbus_parse_rtu_response(resp_buf, 8, &req, &resp);
    if (rc != MB_OK) FAIL("parse failed");
    if (resp.written_addr != 0x0001) FAIL("addr");
    if (resp.written_count != 3) FAIL("count");
    PASS();
}

void test_expected_len(void) {
    TEST("expected_frame_length");
    /* FC=03 响应: 需要第3字节判断 */
    uint8_t resp3[] = {0x01, 0x03, 0x04}; /* byte_count=4 → len=3+4+2=9 */
    int32_t elen = modbus_rtu_expected_len(resp3, 3);
    if (elen != 9) FAIL("FC=03 expected 9");

    /* FC=06: 固定 8 字节 */
    uint8_t resp6[] = {0x01, 0x06};
    elen = modbus_rtu_expected_len(resp6, 2);
    if (elen != 8) FAIL("FC=06 expected 8");

    /* 异常响应: 5 字节 */
    uint8_t exc[] = {0x01, 0x83};
    elen = modbus_rtu_expected_len(exc, 2);
    if (elen != 5) FAIL("exception expected 5");

    /* 数据不足 */
    elen = modbus_rtu_expected_len(resp3, 2); /* 只有 slave+fc, FC=03 需要 byte_count */
    if (elen != 0) FAIL("insufficient data should return 0");
    PASS();
}

void test_roundtrip(void) {
    TEST("roundtrip_build_parse");
    /* 构建 → 解析 → 验证一致性 */
    uint8_t buf[32];
    uint16_t orig_regs[] = {0x1111, 0x2222, 0x3333, 0x4444, 0x5555};
    int32_t len = modbus_build_read_holding_response(buf, sizeof(buf), 0x0A, orig_regs, 5);
    if (len < 0) FAIL("build failed");

    modbus_request_t req = {.slave_id=0x0A, .function_code=3, .reg_count=5};
    modbus_response_t resp;
    int32_t rc = modbus_parse_rtu_response(buf, len, &req, &resp);
    if (rc != MB_OK) FAIL("parse failed");
    if (resp.reg_count != 5) FAIL("reg_count");
    for (int i = 0; i < 5; i++) {
        if (resp.registers[i] != orig_regs[i]) FAIL("reg mismatch");
    }
    PASS();
}

int main(void) {
    printf("=== Modbus RTU Codec Unit Tests ===\n");
    test_build_read_holding();
    test_parse_read_response();
    test_exception_response();
    test_crc_error_detection();
    test_slave_mismatch();
    test_write_single();
    test_write_multi();
    test_expected_len();
    test_roundtrip();
    printf("\nResults: %d/%d passed\n", tests_pass, tests_run);
    return tests_pass == tests_run ? 0 : 1;
}
