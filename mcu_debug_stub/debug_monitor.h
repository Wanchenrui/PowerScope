/**
 * debug_monitor.h — MCU 端调试桩接口 (可移植到固件)
 */
#ifndef DEBUG_MONITOR_H
#define DEBUG_MONITOR_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ====== 配置宏 (可裁剪) ====== */
#ifndef DBG_ENABLE
#define DBG_ENABLE          1
#endif
#define DM_MAX_SAMPLE_ITEM  32
#define DM_MAX_LISTS        2
#define DM_STREAM_BUF_SIZE  512
#define DM_UART_RX_BUF      256

/* ====== 协议常量 ====== */
#define DM_SOF0  0xA5
#define DM_SOF1  0x5A

/* ====== 类型定义 ====== */
typedef struct {
    uint32_t address;
    uint8_t  size;
    uint8_t  reserved;
} dm_sample_item_t;

typedef struct {
    dm_sample_item_t items[DM_MAX_SAMPLE_ITEM];
    uint8_t  count;
    uint16_t period_us;
    bool     enabled;
    volatile uint16_t seq;
    uint32_t last_tick;
} dm_sample_list_t;

typedef struct {
    char     mcu_model[32];
    uint32_t cpu_freq_hz;
    uint32_t elf_crc;
    uint16_t protocol_ver;
    char     fw_version[16];
} dm_device_info_t;

typedef struct {
    uint32_t frames_received;
    uint32_t frames_processed;
    uint32_t crc_errors;
    uint32_t stream_frames_sent;
    uint32_t addr_errors;
} dm_stats_t;

/* ====== 公共接口 ====== */
void debug_monitor_init(void);
void debug_monitor_feed_byte(uint8_t byte);
void debug_monitor_on_tick(void);
const dm_device_info_t* debug_monitor_get_info(void);
void debug_monitor_set_info(const dm_device_info_t* info);
const dm_stats_t* debug_monitor_get_stats(void);

/** 添加可访问内存区域 (扩展默认保护表) */
void debug_monitor_add_region(uint32_t start, uint32_t end, uint8_t perm);

/** 设置地址解析器 (将 32 位 MCU 地址映射到实际内存指针) */
typedef void* (*dm_addr_resolver_t)(uint32_t addr);
void debug_monitor_set_addr_resolver(dm_addr_resolver_t resolver);

/** CRC16-Modbus 计算 (用于验证, 与 power_core 的 crc16_modbus 一致) */
uint16_t dm_crc16_public(const uint8_t* data, uint32_t len);

/* ====== 硬件抽象层 (需用户移植) ====== */
void dbg_uart_send(const uint8_t* data, uint16_t len);
uint32_t dbg_get_timestamp_us(void);
void dbg_system_reset(void);

#ifdef __cplusplus
}
#endif
#endif /* DEBUG_MONITOR_H */
