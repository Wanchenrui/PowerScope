/**
 * test_debug_monitor.c — MCU 调试桩单元测试
 *
 * 使用模拟 MCU 地址 (0x20000000+) 映射到 PC 内存, 验证调试桩协议。
 */
#include "../debug_monitor.h"
#include "../../power_core/include/debug_protocol.h"
#include "../../power_core/include/crc16_table.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static int tests_run = 0;
static int tests_pass = 0;
#define TEST(name) do { tests_run++; printf("  [TEST] %s ... ", name); } while(0)
#define PASS() do { tests_pass++; printf("PASS\n"); } while(0)
#define FAIL(msg) do { printf("FAIL: %s\n", msg); return; } while(0)

/* ====== 模拟 MCU 内存: 地址 0x20000000 映射到此数组 ====== */
#define MCU_MEM_BASE 0x20000000u
static uint8_t g_mcu_mem[4096];

/* 地址解析器: 32位 MCU 地址 → PC 指针 */
static void* test_addr_resolver(uint32_t addr) {
    if (addr >= MCU_MEM_BASE && addr < MCU_MEM_BASE + sizeof(g_mcu_mem)) {
        return &g_mcu_mem[addr - MCU_MEM_BASE];
    }
    return NULL;
}

/* ====== Mock HAL ====== */
static uint8_t s_tx_buf[2048];
static uint16_t s_tx_len;
static bool s_reset_called;

void dbg_uart_send(const uint8_t* data, uint16_t len) {
    if (s_tx_len + len <= sizeof(s_tx_buf)) {
        memcpy(s_tx_buf + s_tx_len, data, len);
        s_tx_len += len;
    }
}
uint32_t dbg_get_timestamp_us(void) { return 12345; }
void dbg_system_reset(void) { s_reset_called = true; }

static void tx_clear(void) { s_tx_len = 0; s_reset_called = false; }

static bool parse_resp(uint8_t* cmd, uint16_t* seq, uint8_t* status,
                       uint8_t* payload, uint16_t* plen) {
    if (s_tx_len < 11) return false;
    if (s_tx_buf[0] != DM_SOF0 || s_tx_buf[1] != DM_SOF1) return false;
    *cmd = s_tx_buf[3];
    *seq = s_tx_buf[4] | (s_tx_buf[5] << 8);
    *status = s_tx_buf[6];
    *plen = s_tx_buf[7] | (s_tx_buf[8] << 8);
    if (*plen > 0 && payload) memcpy(payload, s_tx_buf + 9, *plen);
    uint16_t crc_calc = crc16_modbus(s_tx_buf, 9 + *plen);
    uint16_t crc_recv = s_tx_buf[9 + *plen] | (s_tx_buf[10 + *plen] << 8);
    return crc_calc == crc_recv;
}

static void send_frame(uint8_t cmd, uint16_t seq, uint32_t addr,
                       const uint8_t* payload, uint16_t plen) {
    uint8_t buf[512];
    int32_t len = dbg_build_frame(buf, sizeof(buf), cmd, seq, addr, payload, plen);
    if (len < 0) return;
    for (int32_t i = 0; i < len; i++) debug_monitor_feed_byte(buf[i]);
}

void test_get_info(void) {
    TEST("get_info");
    tx_clear();
    send_frame(DBG_CMD_GET_INFO, 0x0001, 0, NULL, 0);
    uint8_t cmd, status, payload[256]; uint16_t seq, plen;
    if (!parse_resp(&cmd, &seq, &status, payload, &plen)) FAIL("no response");
    if (cmd != DBG_CMD_GET_INFO) FAIL("cmd");
    if (seq != 0x0001) FAIL("seq");
    if (status != 0) FAIL("status");
    if (plen != sizeof(dm_device_info_t)) FAIL("payload size");
    PASS();
}

void test_read_mem(void) {
    TEST("read_mem");
    g_mcu_mem[0] = 0xDE; g_mcu_mem[1] = 0xAD;
    g_mcu_mem[2] = 0xBE; g_mcu_mem[3] = 0xEF;
    uint8_t read_len = 4;
    tx_clear();
    send_frame(DBG_CMD_READ_MEM, 0x0002, MCU_MEM_BASE, &read_len, 1);
    uint8_t cmd, status, payload[256]; uint16_t seq, plen;
    if (!parse_resp(&cmd, &seq, &status, payload, &plen)) {
        char msg[64]; sprintf(msg, "no response, tx_len=%d", s_tx_len); FAIL(msg);
    }
    if (status != 0) {
        char msg[64]; sprintf(msg, "status=%d cmd=%d tx_len=%d", status, cmd, s_tx_len); FAIL(msg);
    }
    if (plen != 4) FAIL("len");
    if (payload[0]!=0xDE || payload[1]!=0xAD || payload[2]!=0xBE || payload[3]!=0xEF)
        FAIL("data mismatch");
    PASS();
}

void test_write_mem(void) {
    TEST("write_mem");
    uint8_t wdata[] = {0x12, 0x34, 0x56, 0x78};
    tx_clear();
    send_frame(DBG_CMD_WRITE_MEM, 0x0003, MCU_MEM_BASE + 16, wdata, 4);
    uint8_t cmd, status; uint16_t seq, plen;
    if (!parse_resp(&cmd, &seq, &status, NULL, &plen)) FAIL("no response");
    if (status != 0) FAIL("status");
    if (g_mcu_mem[16]!=0x12 || g_mcu_mem[17]!=0x34 ||
        g_mcu_mem[18]!=0x56 || g_mcu_mem[19]!=0x78) FAIL("write failed");
    PASS();
}

void test_set_sample_list(void) {
    TEST("set_sample_list");
    uint8_t payload[4 + 2 * sizeof(dm_sample_item_t)];
    payload[0] = 0;
    payload[1] = 0xE8; payload[2] = 0x03; /* period=1000 */
    payload[3] = 2;
    dm_sample_item_t* items = (dm_sample_item_t*)(payload + 4);
    items[0].address = MCU_MEM_BASE;
    items[0].size = 4;
    items[1].address = MCU_MEM_BASE + 4;
    items[1].size = 2;
    tx_clear();
    send_frame(DBG_CMD_SET_SAMPLE, 0x0004, 0, payload, sizeof(payload));
    uint8_t cmd, status; uint16_t seq, plen;
    if (!parse_resp(&cmd, &seq, &status, NULL, &plen)) FAIL("no response");
    if (status != 0) FAIL("status");
    PASS();
}

void test_start_stop_stream(void) {
    TEST("start_stop_stream");
    uint8_t start_pl[] = {0};
    tx_clear();
    send_frame(DBG_CMD_START_STREAM, 0x0005, 0, start_pl, 1);
    uint8_t cmd, status; uint16_t seq, plen;
    if (!parse_resp(&cmd, &seq, &status, NULL, &plen)) FAIL("start resp");
    if (status != 0) FAIL("start status");
    tx_clear();
    g_mcu_mem[0]=0xAA; g_mcu_mem[1]=0xBB; g_mcu_mem[2]=0xCC; g_mcu_mem[3]=0xDD;
    g_mcu_mem[4]=0x11; g_mcu_mem[5]=0x22;
    debug_monitor_on_tick();
    if (s_tx_len == 0) FAIL("no stream frame");
    if (s_tx_buf[0]!=DM_SOF0 || s_tx_buf[1]!=DM_SOF1) FAIL("stream SOF");
    if (s_tx_buf[3]!=DBG_CMD_STREAM_DATA) FAIL("stream cmd");
    if (s_tx_len != 20) FAIL("stream len");
    tx_clear();
    send_frame(DBG_CMD_STOP_STREAM, 0x0006, 0, start_pl, 1);
    if (!parse_resp(&cmd, &seq, &status, NULL, &plen)) FAIL("stop resp");
    if (status != 0) FAIL("stop status");
    tx_clear();
    debug_monitor_on_tick();
    if (s_tx_len > 0) FAIL("stream after stop");
    PASS();
}

void test_crc_error(void) {
    TEST("crc_error_handling");
    uint8_t buf[64];
    int32_t len = dbg_build_frame(buf, sizeof(buf), DBG_CMD_GET_INFO, 0x01, 0, NULL, 0);
    buf[len - 1] ^= 0xFF;
    tx_clear();
    for (int32_t i = 0; i < len; i++) debug_monitor_feed_byte(buf[i]);
    uint8_t cmd, status; uint16_t seq, plen;
    if (!parse_resp(&cmd, &seq, &status, NULL, &plen)) FAIL("no NACK");
    if (cmd != DBG_CMD_NACK) FAIL("expected NACK");
    if (status != 1) FAIL("expected CRC error");
    PASS();
}

void test_addr_protection(void) {
    TEST("address_protection");
    uint8_t read_len = 4;
    tx_clear();
    send_frame(DBG_CMD_READ_MEM, 0x0007, 0x08000000, &read_len, 1);
    uint8_t cmd, status; uint16_t seq, plen;
    if (!parse_resp(&cmd, &seq, &status, NULL, &plen)) FAIL("no response");
    if (status != 6) FAIL("expected protected error");
    PASS();
}

void test_unknown_cmd(void) {
    TEST("unknown_command");
    tx_clear();
    send_frame(0x99, 0x0008, 0, NULL, 0);
    uint8_t cmd, status; uint16_t seq, plen;
    if (!parse_resp(&cmd, &seq, &status, NULL, &plen)) FAIL("no response");
    if (cmd != DBG_CMD_NACK) FAIL("expected NACK");
    if (status != 2) FAIL("expected cmd error");
    PASS();
}

void test_stats(void) {
    TEST("stats_tracking");
    const dm_stats_t* stats = debug_monitor_get_stats();
    if (stats->frames_received == 0) FAIL("frames_received should be > 0");
    if (stats->frames_processed == 0) FAIL("frames_processed should be > 0");
    if (stats->crc_errors == 0) FAIL("crc_errors should be > 0");
    PASS();
}

int main(void) {
    printf("=== MCU Debug Monitor Unit Tests ===\n");

    /* CRC 一致性验证 */
    {
        const uint8_t data[] = {0xA5, 0x5A, 0x01, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00, 0x20, 0x01, 0x00, 0x04};
        uint16_t c1 = crc16_modbus(data, 13);
        uint16_t c2 = dm_crc16_public(data, 13);
        printf("[VERIFY] crc16_modbus=%04X dm_crc16=%04X %s\n", c1, c2, c1==c2?"MATCH":"MISMATCH");
    }

    debug_monitor_init();
    debug_monitor_set_addr_resolver(test_addr_resolver);
    test_get_info();
    test_read_mem();
    test_write_mem();
    test_set_sample_list();
    test_start_stop_stream();
    test_crc_error();
    test_addr_protection();
    test_unknown_cmd();
    test_stats();
    printf("\nResults: %d/%d passed\n", tests_pass, tests_run);
    return tests_pass == tests_run ? 0 : 1;
}
