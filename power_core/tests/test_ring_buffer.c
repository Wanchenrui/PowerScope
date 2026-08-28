/**
 * test_ring_buffer.c — 环形缓冲区单元测试
 *
 * 测试策略:
 * 1. 基本写入读取
 * 2. 回绕场景 (写超过容量一半再读再写)
 * 3. 满缓冲区丢弃行为
 * 4. 空缓冲区读取
 * 5. 偷看不消费
 * 6. 2的幂 vs 非幂容量
 * 7. 大量数据压力测试
 */
#include "../include/ring_buffer.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static int tests_run = 0;
static int tests_pass = 0;

#define TEST(name) do { tests_run++; printf("  [TEST] %s ... ", name); } while(0)
#define PASS() do { tests_pass++; printf("PASS\n"); } while(0)
#define FAIL(msg) do { printf("FAIL: %s\n", msg); return; } while(0)

void test_basic_write_read(void) {
    TEST("basic_write_read");
    ring_buffer_t* rb = ring_buffer_create(64);
    if (!rb) FAIL("create failed");
    uint8_t wdata[] = {1, 2, 3, 4, 5};
    uint32_t written = ring_buffer_write(rb, wdata, 5);
    if (written != 5) FAIL("written != 5");
    if (ring_buffer_available(rb) != 5) FAIL("available != 5");
    uint8_t rdata[5] = {0};
    uint32_t read = ring_buffer_read(rb, rdata, 5);
    if (read != 5) FAIL("read != 5");
    if (memcmp(wdata, rdata, 5) != 0) FAIL("data mismatch");
    if (ring_buffer_available(rb) != 0) FAIL("available != 0 after read");
    ring_buffer_destroy(rb);
    PASS();
}

void test_wraparound(void) {
    TEST("wraparound");
    ring_buffer_t* rb = ring_buffer_create(8);
    if (!rb) FAIL("create failed");
    uint8_t wdata[] = {1,2,3,4,5,6,7,8};
    ring_buffer_write(rb, wdata, 8);  /* 写满 */
    uint8_t rdata[4];
    ring_buffer_read(rb, rdata, 4);   /* 读4个, 读指针在4 */
    uint8_t wdata2[] = {9,10,11,12};
    ring_buffer_write(rb, wdata2, 4); /* 写4个, 应该回绕 */
    /* 缓冲区现在: [9,10,11,12,5,6,7,8] read=4, write=12(回绕到4) */
    uint8_t rdata2[8] = {0};
    uint32_t rd = ring_buffer_read(rb, rdata2, 8);
    if (rd != 8) FAIL("expected 8 bytes after wrap");
    uint8_t expected[] = {5,6,7,8,9,10,11,12};
    if (memcmp(rdata2, expected, 8) != 0) FAIL("wrap data mismatch");
    ring_buffer_destroy(rb);
    PASS();
}

void test_full_discard(void) {
    TEST("full_discard");
    ring_buffer_t* rb = ring_buffer_create(4);
    uint8_t wdata[] = {1,2,3,4,5,6};
    uint32_t written = ring_buffer_write(rb, wdata, 6);
    if (written != 4) FAIL("should only write 4 when capacity=4");
    ring_buffer_destroy(rb);
    PASS();
}

void test_empty_read(void) {
    TEST("empty_read");
    ring_buffer_t* rb = ring_buffer_create(16);
    uint8_t buf[4];
    uint32_t rd = ring_buffer_read(rb, buf, 4);
    if (rd != 0) FAIL("empty read should return 0");
    ring_buffer_destroy(rb);
    PASS();
}

void test_peek(void) {
    TEST("peek_no_consume");
    ring_buffer_t* rb = ring_buffer_create(16);
    uint8_t wdata[] = {10,20,30};
    ring_buffer_write(rb, wdata, 3);
    uint8_t buf[3] = {0};
    ring_buffer_peek(rb, buf, 3);
    if (memcmp(buf, wdata, 3) != 0) FAIL("peek data mismatch");
    if (ring_buffer_available(rb) != 3) FAIL("peek should not consume");
    ring_buffer_destroy(rb);
    PASS();
}

void test_non_power_of_two(void) {
    TEST("non_power_of_two_capacity");
    ring_buffer_t* rb = ring_buffer_create(10); /* 非幂 */
    if (!rb) FAIL("create failed");
    uint8_t wdata[10];
    for (int i = 0; i < 10; i++) wdata[i] = (uint8_t)(i + 1);
    ring_buffer_write(rb, wdata, 10);
    /* 读5, 写5, 回绕测试 */
    uint8_t rdata[5];
    ring_buffer_read(rb, rdata, 5);
    uint8_t wdata2[] = {11,12,13,14,15};
    ring_buffer_write(rb, wdata2, 5);
    uint8_t rdata2[10] = {0};
    uint32_t rd = ring_buffer_read(rb, rdata2, 10);
    if (rd != 10) FAIL("expected 10 bytes");
    uint8_t expected[] = {6,7,8,9,10,11,12,13,14,15};
    if (memcmp(rdata2, expected, 10) != 0) FAIL("non-power-of-2 wrap mismatch");
    ring_buffer_destroy(rb);
    PASS();
}

void test_stress(void) {
    TEST("stress_10000_ops");
    ring_buffer_t* rb = ring_buffer_create(1024);
    if (!rb) FAIL("create failed");
    uint8_t wbuf[256], rbuf[256];
    uint32_t total_written = 0, total_read = 0;
    uint32_t seed = 42;
    for (int i = 0; i < 10000; i++) {
        seed = seed * 1103515245 + 12345;
        int len = (seed >> 16) % 200 + 1;
        for (int j = 0; j < len; j++) wbuf[j] = (uint8_t)((seed + j) & 0xFF);
        uint32_t w = ring_buffer_write(rb, wbuf, len);
        total_written += w;
        seed = seed * 1103515245 + 12345;
        int rlen = (seed >> 16) % 200 + 1;
        uint32_t r = ring_buffer_read(rb, rbuf, rlen);
        total_read += r;
        /* available 应等于 total_written - total_read */
        uint32_t avail = ring_buffer_available(rb);
        if (avail != total_written - total_read) FAIL("available mismatch in stress");
        /* free 应等于 capacity - available */
        uint32_t free_s = ring_buffer_free_space(rb);
        if (free_s != 1024 - avail) FAIL("free space mismatch in stress");
    }
    ring_buffer_destroy(rb);
    PASS();
}

void test_clear(void) {
    TEST("clear");
    ring_buffer_t* rb = ring_buffer_create(32);
    uint8_t data[] = {1,2,3};
    ring_buffer_write(rb, data, 3);
    ring_buffer_clear(rb);
    if (ring_buffer_available(rb) != 0) FAIL("available != 0 after clear");
    if (ring_buffer_free_space(rb) != 32) FAIL("free != capacity after clear");
    ring_buffer_destroy(rb);
    PASS();
}

int main(void) {
    printf("=== Ring Buffer Unit Tests ===\n");
    test_basic_write_read();
    test_wraparound();
    test_full_discard();
    test_empty_read();
    test_peek();
    test_non_power_of_two();
    test_stress();
    test_clear();
    printf("\nResults: %d/%d passed\n", tests_pass, tests_run);
    return tests_pass == tests_run ? 0 : 1;
}
