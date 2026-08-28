/**
 * test_crc16.c — CRC16-Modbus 单元测试
 *
 * 测试策略:
 * 1. 已知向量测试 (Modbus 标准测试数据)
 * 2. 查表法 vs 逐位法 一致性验证
 * 3. 续算功能验证
 * 4. 空数据/边界条件
 */
#include "../include/crc16_table.h"
#include <stdio.h>
#include <string.h>
#include <assert.h>

static int tests_run = 0;
static int tests_pass = 0;

#define TEST(name) do { tests_run++; printf("  [TEST] %s ... ", name); } while(0)
#define PASS() do { tests_pass++; printf("PASS\n"); } while(0)
#define FAIL(msg) do { printf("FAIL: %s\n", msg); return; } while(0)

/* Modbus 标准测试向量: "123456789" → CRC = 0x4B37 */
void test_known_vector(void) {
    TEST("known_vector_123456789");
    const uint8_t data[] = {'1','2','3','4','5','6','7','8','9'};
    uint16_t crc = crc16_modbus(data, 9);
    if (crc != 0x4B37) {
        char msg[64];
        sprintf(msg, "expected 0x4B37, got 0x%04X", crc);
        FAIL(msg);
    }
    PASS();
}

/* 单字节测试: 0x01 → CRC = 0xC0C1 不对... 让我算一下
 * crc=0xFFFF, data=0x01
 * crc = (0xFFFF >> 8) ^ table[(0xFFFF ^ 0x01) & 0xFF]
 *     = 0x00FF ^ table[0xFE]
 *     = 0x00FF ^ 0x4040
 *     = 0x40BF
 * 实际上让我用已知值。Modbus 单字节 0x00 → 0xFFFF 不变？不对。
 * crc=0xFFFF, data=0x00
 * crc = (0xFFFF >> 8) ^ table[(0xFFFF ^ 0x00) & 0xFF]
 *     = 0x00FF ^ table[0xFF]
 *     = 0x00FF ^ 0x4040  不对, table[0xFF] = 0x4040
 *     = 0x40BF
 * 让我用程序算，不要手算。
 */
void test_single_byte(void) {
    TEST("single_byte_consistency");
    for (uint16_t i = 0; i < 256; i++) {
        uint8_t byte = (uint8_t)i;
        uint16_t t = crc16_modbus(&byte, 1);
        uint16_t b = crc16_modbus_bitwise(&byte, 1);
        if (t != b) {
            char msg[80];
            sprintf(msg, "byte 0x%02X: table=0x%04X bitwise=0x%04X", byte, t, b);
            FAIL(msg);
        }
    }
    PASS();
}

/* 查表法 vs 逐位法 大量随机数据一致性 */
void test_table_vs_bitwise(void) {
    TEST("table_vs_bitwise_random");
    uint8_t data[256];
    /* 用简单 LCG 生成伪随机数据 */
    uint32_t seed = 12345;
    for (int iter = 0; iter < 100; iter++) {
        for (int i = 0; i < 256; i++) {
            seed = seed * 1103515245 + 12345;
            data[i] = (uint8_t)(seed >> 16);
        }
        uint16_t t = crc16_modbus(data, 256);
        uint16_t b = crc16_modbus_bitwise(data, 256);
        if (t != b) {
            char msg[80];
            sprintf(msg, "iter %d: table=0x%04X bitwise=0x%04X", iter, t, b);
            FAIL(msg);
        }
    }
    PASS();
}

/* 续算功能: 分片计算应等于整块计算 */
void test_continue(void) {
    TEST("continue_split_calc");
    const uint8_t data[] = {0x01, 0x04, 0x02, 0xFF, 0xFF};
    uint16_t whole = crc16_modbus(data, 5);
    uint16_t part = crc16_modbus_continue(0xFFFF, data, 2);
    part = crc16_modbus_continue(part, data + 2, 3);
    if (whole != part) {
        char msg[80];
        sprintf(msg, "whole=0x%04X split=0x%04X", whole, part);
        FAIL(msg);
    }
    PASS();
}

/* 空数据: CRC 应为初始值 0xFFFF */
void test_empty(void) {
    TEST("empty_data");
    uint16_t crc = crc16_modbus((const uint8_t*)"", 0);
    if (crc != 0xFFFF) {
        char msg[64];
        sprintf(msg, "expected 0xFFFF, got 0x%04X", crc);
        FAIL(msg);
    }
    PASS();
}

/* Modbus RTU 实际帧测试: 请求 0x01 0x03 0x00 0x00 0x00 0x0A → CRC = 0xC5CD */
void test_modbus_frame(void) {
    TEST("modbus_rtu_frame");
    const uint8_t frame[] = {0x01, 0x03, 0x00, 0x00, 0x00, 0x0A};
    uint16_t crc = crc16_modbus(frame, 6);
    /* Modbus CRC 低字节先发, 高字节后发
     * 0x01 03 00 00 00 0A C5 CD → CRC = 0xCDC5 */
    if (crc != 0xCDC5) {
        char msg[80];
        sprintf(msg, "expected 0xCDC5, got 0x%04X", crc);
        FAIL(msg);
    }
    PASS();
}

int main(void) {
    printf("=== CRC16-Modbus Unit Tests ===\n");
    test_known_vector();
    test_single_byte();
    test_table_vs_bitwise();
    test_continue();
    test_empty();
    test_modbus_frame();
    printf("\nResults: %d/%d passed\n", tests_pass, tests_run);
    return tests_pass == tests_run ? 0 : 1;
}
