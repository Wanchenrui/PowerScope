/**
 * test_debug_protocol.c — 调试协议引擎单元测试
 *
 * 测试策略:
 * 1. 命令帧 build → parse roundtrip
 * 2. 响应帧 build → parse
 * 3. 流式帧 build → parse roundtrip
 * 4. CRC 错误检测
 * 5. 帧头校验
 * 6. 期望帧长判断
 * 7. 各种 payload 大小
 * 8. 全命令码覆盖
 */
#include "../include/debug_protocol.h"
#include "../include/crc16_table.h"
#include <stdio.h>
#include <string.h>

static int tests_run = 0;
static int tests_pass = 0;

#define TEST(name) do { tests_run++; printf("  [TEST] %s ... ", name); } while(0)
#define PASS() do { tests_pass++; printf("PASS\n"); } while(0)
#define FAIL(msg) do { printf("FAIL: %s\n", msg); return; } while(0)

void test_cmd_frame_roundtrip(void) {
    TEST("cmd_frame_roundtrip");
    uint8_t buf[256];
    uint8_t payload[] = {0xDE, 0xAD, 0xBE, 0xEF};
    int32_t len = dbg_build_frame(buf, sizeof(buf), DBG_CMD_READ_MEM,
                                  0x1234, 0x20001000, payload, 4);
    if (len < 0) FAIL("build failed");
    if (len != DBG_HDR_SIZE + 4 + DBG_CRC_SIZE) FAIL("len mismatch");

    dbg_frame_t frame;
    int32_t rc = dbg_parse_frame(buf, len, &frame);
    if (rc != DBG_ST_OK) FAIL("parse failed");
    if (frame.cmd != DBG_CMD_READ_MEM) FAIL("cmd");
    if (frame.seq != 0x1234) FAIL("seq");
    if (frame.address != 0x20001000) FAIL("address");
    if (frame.payload_len != 4) FAIL("payload_len");
    if (memcmp(frame.payload, payload, 4) != 0) FAIL("payload mismatch");
    PASS();
}

void test_empty_payload(void) {
    TEST("empty_payload");
    uint8_t buf[64];
    int32_t len = dbg_build_frame(buf, sizeof(buf), DBG_CMD_GET_INFO,
                                  0x0001, 0, NULL, 0);
    if (len != DBG_HDR_SIZE + DBG_CRC_SIZE) FAIL("len");
    if (len != 14) FAIL("expected 14");

    dbg_frame_t frame;
    int32_t rc = dbg_parse_frame(buf, len, &frame);
    if (rc != DBG_ST_OK) FAIL("parse");
    if (frame.payload_len != 0) FAIL("payload_len != 0");
    if (frame.cmd != DBG_CMD_GET_INFO) FAIL("cmd");
    PASS();
}

void test_large_payload(void) {
    TEST("large_payload_256");
    uint8_t buf[512];
    uint8_t payload[256];
    for (int i = 0; i < 256; i++) payload[i] = (uint8_t)(i ^ 0xAA);

    int32_t len = dbg_build_frame(buf, sizeof(buf), DBG_CMD_WRITE_MEM,
                                  0x00FF, 0x20000000, payload, 256);
    if (len < 0) FAIL("build failed");

    dbg_frame_t frame;
    int32_t rc = dbg_parse_frame(buf, len, &frame);
    if (rc != DBG_ST_OK) FAIL("parse");
    if (frame.payload_len != 256) FAIL("payload_len");
    if (memcmp(frame.payload, payload, 256) != 0) FAIL("payload mismatch");
    PASS();
}

void test_crc_error(void) {
    TEST("crc_error_detection");
    uint8_t buf[64];
    int32_t len = dbg_build_frame(buf, sizeof(buf), DBG_CMD_READ_MEM,
                                  0x01, 0x20000000, NULL, 0);
    buf[4] ^= 0xFF; /* 破坏 SEQ 字段 */

    dbg_frame_t frame;
    int32_t rc = dbg_parse_frame(buf, len, &frame);
    if (rc != DBG_ST_ERR_CRC) FAIL("expected CRC error");
    PASS();
}

void test_bad_sof(void) {
    TEST("bad_sof_detection");
    uint8_t buf[64];
    int32_t len = dbg_build_frame(buf, sizeof(buf), DBG_CMD_READ_MEM,
                                  0x01, 0, NULL, 0);
    buf[0] = 0x00; /* 破坏 SOF */

    dbg_frame_t frame;
    int32_t rc = dbg_parse_frame(buf, len, &frame);
    if (rc != DBG_ST_ERR_CMD) FAIL("expected CMD error (bad SOF)");
    PASS();
}

void test_response_frame(void) {
    TEST("response_frame_roundtrip");
    uint8_t buf[256];
    uint8_t resp_data[] = {0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0};
    int32_t len = dbg_build_response(buf, sizeof(buf), DBG_CMD_READ_MEM,
                                     0x0042, DBG_ST_OK, resp_data, 8);
    if (len < 0) FAIL("build failed");
    /* 响应帧: SOF(2)+VER(1)+CMD(1)+SEQ(2)+STATUS(1)+LEN(2)+PAYLOAD(8)+CRC(2) = 19 */
    if (len != 19) FAIL("expected 19");

    /* 验证字段 */
    if (buf[0] != DBG_SOF0 || buf[1] != DBG_SOF1) FAIL("SOF");
    if (buf[3] != DBG_CMD_READ_MEM) FAIL("cmd");
    if (buf[4] != 0x42 || buf[5] != 0x00) FAIL("seq");
    if (buf[6] != DBG_ST_OK) FAIL("status");
    if (buf[7] != 8 || buf[8] != 0) FAIL("len");
    if (memcmp(buf + 9, resp_data, 8) != 0) FAIL("payload");

    /* CRC 校验 */
    uint16_t crc_calc = crc16_modbus(buf, 9 + 8);
    uint16_t crc_recv = buf[17] | (buf[18] << 8);
    if (crc_calc != crc_recv) FAIL("CRC mismatch");
    PASS();
}

void test_response_nack(void) {
    TEST("response_nack");
    uint8_t buf[64];
    int32_t len = dbg_build_response(buf, sizeof(buf), DBG_CMD_NACK,
                                     0x0099, DBG_ST_ERR_PROTECTED, NULL, 0);
    if (len < 0) FAIL("build failed");
    if (buf[3] != DBG_CMD_NACK) FAIL("cmd");
    if (buf[6] != DBG_ST_ERR_PROTECTED) FAIL("status");
    PASS();
}

void test_stream_frame(void) {
    TEST("stream_frame_roundtrip");
    uint8_t buf[256];
    uint8_t sample_data[] = {
        0x00, 0x00, 0x80, 0x3F,  /* float 1.0 */
        0x00, 0x00, 0x00, 0x40,  /* float 2.0 */
        0x00, 0x00, 0x40, 0x40,  /* float 3.0 */
    };
    int32_t len = dbg_build_stream_frame(buf, sizeof(buf),
                                         0x0007, 0x00123456, 0, 1,
                                         sample_data, 12);
    if (len < 0) FAIL("build failed");
    /* 流式帧: SOF(2)+VER(1)+CMD(1)+SEQ(2)+TS(4)+LIST(1)+COUNT(1)+DATA(12)+CRC(2) = 26 */
    if (len != 26) FAIL("expected 26");

    uint16_t seq; uint32_t ts; uint8_t list_id, count;
    const uint8_t* payload; uint16_t plen;
    int32_t rc = dbg_parse_stream_frame(buf, len, &seq, &ts, &list_id, &count,
                                        &payload, &plen);
    if (rc != DBG_ST_OK) FAIL("parse failed");
    if (seq != 0x0007) FAIL("seq");
    if (ts != 0x00123456) FAIL("timestamp");
    if (list_id != 0) FAIL("list_id");
    if (count != 1) FAIL("count");
    if (plen != 12) FAIL("payload_len");
    if (memcmp(payload, sample_data, 12) != 0) FAIL("payload mismatch");
    PASS();
}

void test_stream_crc_error(void) {
    TEST("stream_frame_crc_error");
    uint8_t buf[256];
    uint8_t data[] = {0x01, 0x02};
    int32_t len = dbg_build_stream_frame(buf, sizeof(buf), 1, 100, 0, 1, data, 2);
    buf[12] ^= 0xFF; /* 破坏数据 */

    uint16_t seq; uint32_t ts; uint8_t lid, cnt;
    const uint8_t* pl; uint16_t plen;
    int32_t rc = dbg_parse_stream_frame(buf, len, &seq, &ts, &lid, &cnt, &pl, &plen);
    if (rc != DBG_ST_ERR_CRC) FAIL("expected CRC error");
    PASS();
}

void test_expected_frame_len(void) {
    TEST("expected_frame_length");
    uint8_t buf[64];
    /* 构建 payload=4 的帧 */
    uint8_t payload[] = {1, 2, 3, 4};
    int32_t len = dbg_build_frame(buf, sizeof(buf), DBG_CMD_WRITE_MEM,
                                  0, 0, payload, 4);
    /* 期望长度 = 12 + 4 + 2 = 18 */
    uint32_t elen = dbg_expected_frame_len(buf, DBG_HDR_SIZE);
    if (elen != 18) FAIL("expected 18");
    if (elen != (uint32_t)len) FAIL("elen != actual len");

    /* 数据不足 */
    elen = dbg_expected_frame_len(buf, 5);
    if (elen != 0) FAIL("insufficient data should return 0");
    PASS();
}

void test_all_cmd_codes(void) {
    TEST("all_command_codes");
    uint8_t codes[] = {DBG_CMD_READ_MEM, DBG_CMD_WRITE_MEM, DBG_CMD_READ_BATCH,
                       DBG_CMD_SET_SAMPLE, DBG_CMD_START_STREAM, DBG_CMD_STOP_STREAM,
                       DBG_CMD_GET_INFO, DBG_CMD_SET_PARAM, DBG_CMD_TRIGGER_STEP,
                       DBG_CMD_RESET};
    uint8_t buf[64];
    for (int i = 0; i < (int)sizeof(codes); i++) {
        int32_t len = dbg_build_frame(buf, sizeof(buf), codes[i], (uint16_t)i, 0, NULL, 0);
        if (len < 0) FAIL("build failed");
        dbg_frame_t frame;
        int32_t rc = dbg_parse_frame(buf, len, &frame);
        if (rc != DBG_ST_OK) FAIL("parse failed");
        if (frame.cmd != codes[i]) FAIL("cmd mismatch");
        if (frame.seq != (uint16_t)i) FAIL("seq mismatch");
    }
    PASS();
}

int main(void) {
    printf("=== Debug Protocol Engine Unit Tests ===\n");
    test_cmd_frame_roundtrip();
    test_empty_payload();
    test_large_payload();
    test_crc_error();
    test_bad_sof();
    test_response_frame();
    test_response_nack();
    test_stream_frame();
    test_stream_crc_error();
    test_expected_frame_len();
    test_all_cmd_codes();
    printf("\nResults: %d/%d passed\n", tests_pass, tests_run);
    return tests_pass == tests_run ? 0 : 1;
}
