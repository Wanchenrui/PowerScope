/**
 * mock_mcu.c — 模拟 MCU DLL，封装调试桩供 Python 端到端测试
 *
 * 提供模拟 MCU 内存 + mock HAL + 导出接口，让 Python 通过 ctypes
 * 驱动真实 C 调试桩代码，实现 PC↔MCU 全链路集成测试。
 */
#include "../mcu_debug_stub/debug_monitor.h"
#include <string.h>
#include <stdlib.h>

#define EXPORT __declspec(dllexport)
#define MOCK_MEM_SIZE 8192
#define MOCK_TX_BUF_SIZE 65536

/* ====== 模拟 MCU 内存 (地址 0x20000000 起) ====== */
#define MOCK_MEM_BASE 0x20000000u
static uint8_t s_mcu_mem[MOCK_MEM_SIZE];

/* ====== 模拟 TX 缓冲 (捕获 MCU 发送的数据) ====== */
static uint8_t s_tx_buf[MOCK_TX_BUF_SIZE];
static uint16_t s_tx_len;
static uint16_t s_tx_read_idx;  /* Python 读取位置 */

/* ====== 模拟时间戳 ====== */
static uint32_t s_mock_time_us;

/* ====== mock HAL 实现 ====== */
void dbg_uart_send(const uint8_t* data, uint16_t len) {
    if (s_tx_len + len <= MOCK_TX_BUF_SIZE) {
        memcpy(s_tx_buf + s_tx_len, data, len);
        s_tx_len += len;
    }
}

uint32_t dbg_get_timestamp_us(void) {
    return s_mock_time_us;
}

void dbg_system_reset(void) {
    /* 测试中不做真实复位，仅标记 */
}

/* ====== 导出接口 (供 Python ctypes 调用) ====== */

EXPORT void mock_init(void) {
    memset(s_mcu_mem, 0, sizeof(s_mcu_mem));
    s_tx_len = 0;
    s_tx_read_idx = 0;
    s_mock_time_us = 0;
    debug_monitor_init();
    /* 注册模拟内存区域: 0x20000000 ~ 0x20001FFF, 读写权限 */
    debug_monitor_add_region(MOCK_MEM_BASE, MOCK_MEM_BASE + MOCK_MEM_SIZE - 1, 2);
    /* 设置地址解析器 */
    extern void* mock_addr_resolver(uint32_t addr);
    debug_monitor_set_addr_resolver(mock_addr_resolver);
}

/* 地址解析器: MCU 地址 → PC 指针 */
void* mock_addr_resolver(uint32_t addr) {
    if (addr >= MOCK_MEM_BASE && addr < MOCK_MEM_BASE + MOCK_MEM_SIZE) {
        return &s_mcu_mem[addr - MOCK_MEM_BASE];
    }
    return NULL;
}

EXPORT void mock_feed_byte(uint8_t byte) {
    debug_monitor_feed_byte(byte);
}

EXPORT void mock_feed_bytes(const uint8_t* data, uint32_t len) {
    for (uint32_t i = 0; i < len; i++) {
        debug_monitor_feed_byte(data[i]);
    }
}

EXPORT void mock_tick(void) {
    s_mock_time_us += 1000;  /* 模拟 1ms tick */
    debug_monitor_on_tick();
}

EXPORT void mock_set_time(uint32_t time_us) {
    s_mock_time_us = time_us;
}

EXPORT uint32_t mock_get_time(void) {
    return s_mock_time_us;
}

/* 获取 MCU 发送的数据 (TX 缓冲) */
EXPORT uint32_t mock_get_tx_len(void) {
    return s_tx_len;
}

EXPORT uint32_t mock_read_tx(uint8_t* buf, uint32_t buf_size) {
    uint32_t available = s_tx_len - s_tx_read_idx;
    if (available == 0) return 0;
    uint32_t to_read = buf_size < available ? buf_size : available;
    memcpy(buf, s_tx_buf + s_tx_read_idx, to_read);
    s_tx_read_idx += (uint16_t)to_read;
    return to_read;
}

EXPORT uint32_t mock_peek_tx(uint8_t* buf, uint32_t buf_size) {
    uint32_t available = s_tx_len - s_tx_read_idx;
    if (available == 0) return 0;
    uint32_t to_read = buf_size < available ? buf_size : available;
    memcpy(buf, s_tx_buf + s_tx_read_idx, to_read);
    return to_read;
}

EXPORT void mock_clear_tx(void) {
    s_tx_len = 0;
    s_tx_read_idx = 0;
}

/* 直接读写模拟 MCU 内存 (测试设置用，不经过协议) */
EXPORT uint8_t* mock_get_mem_ptr(void) {
    return s_mcu_mem;
}

EXPORT uint32_t mock_get_mem_base(void) {
    return MOCK_MEM_BASE;
}

EXPORT uint32_t mock_get_mem_size(void) {
    return MOCK_MEM_SIZE;
}

EXPORT void mock_mem_write(uint32_t offset, const uint8_t* data, uint32_t len) {
    if (offset + len <= MOCK_MEM_SIZE) {
        memcpy(s_mcu_mem + offset, data, len);
    }
}

EXPORT void mock_mem_read(uint32_t offset, uint8_t* buf, uint32_t len) {
    if (offset + len <= MOCK_MEM_SIZE) {
        memcpy(buf, s_mcu_mem + offset, len);
    }
}

/* 设备信息设置 */
EXPORT void mock_set_device_info(const char* model, uint32_t freq, uint32_t crc, const char* version) {
    dm_device_info_t info;
    memset(&info, 0, sizeof(info));
    if (model) strncpy(info.mcu_model, model, sizeof(info.mcu_model) - 1);
    info.cpu_freq_hz = freq;
    info.elf_crc = crc;
    info.protocol_ver = 0x0001;
    if (version) strncpy(info.fw_version, version, sizeof(info.fw_version) - 1);
    debug_monitor_set_info(&info);
}

/* 获取统计信息 */
EXPORT const dm_stats_t* mock_get_stats(void) {
    return debug_monitor_get_stats();
}

/* 获取设备信息 */
EXPORT const dm_device_info_t* mock_get_device_info(void) {
    return debug_monitor_get_info();
}
