/**
 * debug_monitor.c — MCU 端调试桩核心逻辑 (平台无关)
 *
 * 接收状态机解析帧 → 命令处理 → 响应/流式上报
 * 采样列表在 on_tick() 中执行 (定时器中断, 时序精确)
 */
#include "debug_monitor.h"
#include <string.h>

/* CRC16-Modbus (内联实现, MCU 端独立, 不依赖 power_core) */
static const uint16_t s_crc16_table[256] = {
    0x0000,0xC0C1,0xC181,0x0140,0xC301,0x03C0,0x0280,0xC241,
    0xC601,0x06C0,0x0780,0xC741,0x0500,0xC5C1,0xC481,0x0440,
    0xCC01,0x0CC0,0x0D80,0xCD41,0x0F00,0xCFC1,0xCE81,0x0E40,
    0x0A00,0xCAC1,0xCB81,0x0B40,0xC901,0x09C0,0x0880,0xC841,
    0xD801,0x18C0,0x1980,0xD941,0x1B00,0xDBC1,0xDA81,0x1A40,
    0x1E00,0xDEC1,0xDF81,0x1F40,0xDD01,0x1DC0,0x1C80,0xDC41,
    0x1400,0xD4C1,0xD581,0x1540,0xD701,0x17C0,0x1680,0xD641,
    0xD201,0x12C0,0x1380,0xD341,0x1100,0xD1C1,0xD081,0x1040,
    0xF001,0x30C0,0x3180,0xF141,0x3300,0xF3C1,0xF281,0x3240,
    0x3600,0xF6C1,0xF781,0x3740,0xF501,0x35C0,0x3480,0xF441,
    0x3C00,0xFCC1,0xFD81,0x3D40,0xFF01,0x3FC0,0x3E80,0xFE41,
    0xFA01,0x3AC0,0x3B80,0xFB41,0x3900,0xF9C1,0xF881,0x3840,
    0x2800,0xE8C1,0xE981,0x2940,0xEB01,0x2BC0,0x2A80,0xEA41,
    0xEE01,0x2EC0,0x2F80,0xEF41,0x2D00,0xEDC1,0xEC81,0x2C40,
    0xE401,0x24C0,0x2580,0xE541,0x2700,0xE7C1,0xE681,0x2640,
    0x2200,0xE2C1,0xE381,0x2340,0xE101,0x21C0,0x2080,0xE041,
    0xA001,0x60C0,0x6180,0xA141,0x6300,0xA3C1,0xA281,0x6240,
    0x6600,0xA6C1,0xA781,0x6740,0xA501,0x65C0,0x6480,0xA441,
    0x6C00,0xACC1,0xAD81,0x6D40,0xAF01,0x6FC0,0x6E80,0xAE41,
    0xAA01,0x6AC0,0x6B80,0xAB41,0x6900,0xA9C1,0xA881,0x6840,
    0x7800,0xB8C1,0xB981,0x7940,0xBB01,0x7BC0,0x7A80,0xBA41,
    0xBE01,0x7EC0,0x7F80,0xBF41,0x7D00,0xBDC1,0xBC81,0x7C40,
    0xB401,0x74C0,0x7580,0xB541,0x7700,0xB7C1,0xB681,0x7640,
    0x7200,0xB2C1,0xB381,0x7340,0xB101,0x71C0,0x7080,0xB041,
    0x5000,0x90C1,0x9181,0x5140,0x9301,0x53C0,0x5280,0x9241,
    0x9601,0x56C0,0x5780,0x9741,0x5500,0x95C1,0x9481,0x5440,
    0x9C01,0x5CC0,0x5D80,0x9D41,0x5F00,0x9FC1,0x9E81,0x5E40,
    0x5A00,0x9AC1,0x9B81,0x5B40,0x9901,0x59C0,0x5880,0x9841,
    0x8801,0x48C0,0x4980,0x8941,0x4B00,0x8BC1,0x8A81,0x4A40,
    0x4E00,0x8EC1,0x8F81,0x4F40,0x8D01,0x4DC0,0x4C80,0x8C41,
    0x4400,0x84C1,0x8581,0x4540,0x8701,0x47C0,0x4680,0x8641,
    0x8201,0x42C0,0x4380,0x8341,0x4100,0x81C1,0x8081,0x4040,
};

static uint16_t dm_crc16(const uint8_t* data, uint32_t len) {
    uint16_t crc = 0xFFFF;
    while (len--) crc = (crc >> 8) ^ s_crc16_table[(crc ^ *data++) & 0xFF];
    return crc;
}
uint16_t dm_crc16_public(const uint8_t* data, uint32_t len) { return dm_crc16(data, len); }

/* ====== 命令码 ====== */
enum {
    DM_CMD_READ_MEM=0x01, DM_CMD_WRITE_MEM=0x02, DM_CMD_READ_BATCH=0x03,
    DM_CMD_SET_SAMPLE=0x04, DM_CMD_START_STREAM=0x05, DM_CMD_STOP_STREAM=0x06,
    DM_CMD_GET_INFO=0x07, DM_CMD_SET_PARAM=0x08, DM_CMD_TRIGGER_STEP=0x09,
    DM_CMD_RESET=0x0A, DM_CMD_STREAM_DATA=0x10, DM_CMD_NACK=0xFF,
};

/* ====== 状态码 ====== */
enum {
    DM_ST_OK=0, DM_ST_ERR_CRC, DM_ST_ERR_CMD, DM_ST_ERR_ADDR,
    DM_ST_ERR_LEN, DM_ST_ERR_BUSY, DM_ST_ERR_PROTECTED, DM_ST_ERR_LIST_FULL,
};

/* ====== 地址解析器 (32位MCU地址 → 实际指针) ====== */
static dm_addr_resolver_t s_addr_resolver = NULL;
void debug_monitor_set_addr_resolver(dm_addr_resolver_t resolver) {
    s_addr_resolver = resolver;
}
static inline void* dm_resolve(uint32_t addr) {
    if (s_addr_resolver) return s_addr_resolver(addr);
    return (void*)(uintptr_t)addr;
}

/* ====== 地址保护表 (可扩展) ====== */
#define DM_MAX_REGIONS 16
typedef struct { uint32_t start, end; uint8_t perm; } mem_region_t;
static mem_region_t s_regions[DM_MAX_REGIONS] = {
    {0x20000000, 0x2000FFFF, 2},
    {0x24000000, 0x2407FFFF, 2},
    {0x08000000, 0x081FFFFF, 0},
};
static uint32_t s_region_count = 3;

void debug_monitor_add_region(uint32_t start, uint32_t end, uint8_t perm) {
    if (s_region_count < DM_MAX_REGIONS) {
        s_regions[s_region_count].start = start;
        s_regions[s_region_count].end = end;
        s_regions[s_region_count].perm = perm;
        s_region_count++;
    }
}

static uint8_t check_perm(uint32_t addr, bool write) {
    for (uint32_t i = 0; i < s_region_count; i++) {
        if (addr >= s_regions[i].start && addr <= s_regions[i].end) {
            if (write) return s_regions[i].perm >= 2 ? DM_ST_OK : DM_ST_ERR_PROTECTED;
            return s_regions[i].perm >= 1 ? DM_ST_OK : DM_ST_ERR_PROTECTED;
        }
    }
    return DM_ST_ERR_ADDR;
}

/* ====== 接收状态机 ====== */
typedef enum { RCV_SOF0, RCV_SOF1, RCV_HDR, RCV_PAYLOAD, RCV_CRC } rcv_state_t;

static struct {
    rcv_state_t state;
    uint8_t  buf[DM_UART_RX_BUF];
    uint16_t idx;
    uint16_t payload_len;
    uint8_t  hdr[10]; /* ver(1)+cmd(1)+seq(2)+addr(4)+len(2) = 10 字节 */
    uint8_t  hdr_idx;
} s_rcv;

/* ====== 采样列表 ====== */
static dm_sample_list_t s_lists[DM_MAX_LISTS];
static uint8_t s_stream_buf[DM_STREAM_BUF_SIZE];

/* ====== 设备信息 ====== */
static dm_device_info_t s_info = {
    .mcu_model = "STM32G474",
    .cpu_freq_hz = 170000000,
    .elf_crc = 0,
    .protocol_ver = 0x0001,
    .fw_version = "1.0.0",
};

/* ====== 统计 ====== */
static dm_stats_t s_stats;

const dm_device_info_t* debug_monitor_get_info(void) { return &s_info; }
void debug_monitor_set_info(const dm_device_info_t* info) {
    if (info) memcpy(&s_info, info, sizeof(s_info));
}
const dm_stats_t* debug_monitor_get_stats(void) { return &s_stats; }

/* ====== 小端读写 ====== */
static inline void put_u16_le(uint8_t* p, uint16_t v) {
    p[0]=(uint8_t)(v&0xFF); p[1]=(uint8_t)(v>>8);
}
static inline void put_u32_le(uint8_t* p, uint32_t v) {
    p[0]=(uint8_t)(v&0xFF); p[1]=(uint8_t)(v>>8);
    p[2]=(uint8_t)(v>>16); p[3]=(uint8_t)(v>>24);
}
static inline uint16_t get_u16_le(const uint8_t* p) {
    return (uint16_t)p[0] | ((uint16_t)p[1]<<8);
}
static inline uint32_t get_u32_le(const uint8_t* p) {
    return (uint32_t)p[0] | ((uint32_t)p[1]<<8) | ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24);
}

/* ====== 发送响应帧 ====== */
static uint16_t dm_crc16_continue(uint16_t crc, const uint8_t* data, uint32_t len) {
    while (len--) crc = (crc >> 8) ^ s_crc16_table[(crc ^ *data++) & 0xFF];
    return crc;
}

static void send_response(uint8_t cmd, uint16_t seq, uint8_t status,
                          const uint8_t* payload, uint16_t len) {
    uint8_t hdr[9];
    hdr[0]=DM_SOF0; hdr[1]=DM_SOF1; hdr[2]=0x01;
    hdr[3]=cmd; put_u16_le(hdr+4, seq); hdr[6]=status;
    put_u16_le(hdr+7, len);
    uint16_t crc = dm_crc16(hdr, 9);
    if (len) crc = dm_crc16_continue(crc, payload, len);
    dbg_uart_send(hdr, 9);
    if (len) dbg_uart_send(payload, len);
    uint8_t crcl[2] = { (uint8_t)(crc&0xFF), (uint8_t)(crc>>8) };
    dbg_uart_send(crcl, 2);
}

/* ====== 命令处理 ====== */
static void process_frame(const uint8_t* frame, uint16_t total_len) {
    /* frame: SOF(2)+VER(1)+CMD(1)+SEQ(2)+ADDR(4)+LEN(2)+PAYLOAD+CRC(2) */
    if (total_len < 14) return;
    s_stats.frames_received++;

    uint8_t cmd = frame[3];
    uint16_t seq = get_u16_le(frame+4);
    uint32_t addr = get_u32_le(frame+6);
    uint16_t plen = get_u16_le(frame+10);
    const uint8_t* payload = frame + 12;

    /* CRC 校验 */
    uint16_t crc_calc = dm_crc16(frame, total_len - 2);
    uint16_t crc_recv = get_u16_le(frame + total_len - 2);
#ifdef DM_DEBUG
    printf("[DM] frame:");
    for (uint16_t i = 0; i < total_len && i < 20; i++) printf(" %02X", frame[i]);
    printf("\n");
    printf("[DM] CRC calc=%04X recv=%04X total=%d\n", crc_calc, crc_recv, total_len);
#endif
    if (crc_calc != crc_recv) {
        s_stats.crc_errors++;
        send_response(DM_CMD_NACK, seq, DM_ST_ERR_CRC, NULL, 0);
        return;
    }

    switch (cmd) {
    case DM_CMD_READ_MEM: {
        uint8_t st = check_perm(addr, false);
        if (st != DM_ST_OK) { s_stats.addr_errors++; send_response(DM_CMD_NACK,seq,st,NULL,0); return; }
        if (plen < 1) { send_response(DM_CMD_NACK,seq,DM_ST_ERR_LEN,NULL,0); return; }
        uint16_t read_len = payload[0];
        uint8_t rbuf[256];
        if (read_len > sizeof(rbuf)) { send_response(DM_CMD_NACK,seq,DM_ST_ERR_LEN,NULL,0); return; }
        memcpy(rbuf, dm_resolve(addr), read_len);
        send_response(DM_CMD_READ_MEM, seq, DM_ST_OK, rbuf, read_len);
        break;
    }
    case DM_CMD_WRITE_MEM:
    case DM_CMD_SET_PARAM: {
        uint8_t st = check_perm(addr, true);
        if (st != DM_ST_OK) { s_stats.addr_errors++; send_response(DM_CMD_NACK,seq,st,NULL,0); return; }
        memcpy(dm_resolve(addr), payload, plen);
        send_response(cmd, seq, DM_ST_OK, NULL, 0);
        break;
    }
    case DM_CMD_SET_SAMPLE: {
        if (plen < 4) { send_response(DM_CMD_NACK,seq,DM_ST_ERR_LEN,NULL,0); return; }
        uint8_t list_id = payload[0];
        if (list_id >= DM_MAX_LISTS) { send_response(DM_CMD_NACK,seq,DM_ST_ERR_ADDR,NULL,0); return; }
        dm_sample_list_t* L = &s_lists[list_id];
        L->period_us = get_u16_le(payload+1);
        L->count = payload[3];
        if (L->count > DM_MAX_SAMPLE_ITEM) { send_response(DM_CMD_NACK,seq,DM_ST_ERR_LIST_FULL,NULL,0); return; }
        memcpy(L->items, payload+4, L->count * sizeof(dm_sample_item_t));
        L->seq = 0;
        L->last_tick = 0;
        send_response(DM_CMD_SET_SAMPLE, seq, DM_ST_OK, NULL, 0);
        break;
    }
    case DM_CMD_START_STREAM: {
        if (plen < 1) { send_response(DM_CMD_NACK,seq,DM_ST_ERR_LEN,NULL,0); return; }
        uint8_t list_id = payload[0];
        if (list_id < DM_MAX_LISTS) s_lists[list_id].enabled = true;
        send_response(DM_CMD_START_STREAM, seq, DM_ST_OK, NULL, 0);
        break;
    }
    case DM_CMD_STOP_STREAM: {
        if (plen < 1) { send_response(DM_CMD_NACK,seq,DM_ST_ERR_LEN,NULL,0); return; }
        uint8_t list_id = payload[0];
        if (list_id < DM_MAX_LISTS) s_lists[list_id].enabled = false;
        send_response(DM_CMD_STOP_STREAM, seq, DM_ST_OK, NULL, 0);
        break;
    }
    case DM_CMD_GET_INFO:
        send_response(DM_CMD_GET_INFO, seq, DM_ST_OK, (const uint8_t*)&s_info, sizeof(s_info));
        break;
    case DM_CMD_RESET:
        send_response(DM_CMD_RESET, seq, DM_ST_OK, NULL, 0);
        dbg_system_reset();
        break;
    default:
        send_response(DM_CMD_NACK, seq, DM_ST_ERR_CMD, NULL, 0);
    }
    s_stats.frames_processed++;
}

/* ====== UART 字节喂入 (状态机) ====== */
void debug_monitor_feed_byte(uint8_t byte) {
    switch (s_rcv.state) {
    case RCV_SOF0:
        if (byte == DM_SOF0) s_rcv.state = RCV_SOF1;
        break;
    case RCV_SOF1:
        if (byte == DM_SOF1) { s_rcv.state = RCV_HDR; s_rcv.hdr_idx = 0; }
        else s_rcv.state = RCV_SOF0;
        break;
    case RCV_HDR:
        s_rcv.hdr[s_rcv.hdr_idx++] = byte;
        if (s_rcv.hdr_idx >= 10) {
            s_rcv.payload_len = get_u16_le(s_rcv.hdr + 8);
            /* 组装帧头到 buf */
            s_rcv.buf[0] = DM_SOF0; s_rcv.buf[1] = DM_SOF1;
            memcpy(s_rcv.buf + 2, s_rcv.hdr, 10);
            s_rcv.idx = 0;
            s_rcv.state = (s_rcv.payload_len > 0) ? RCV_PAYLOAD : RCV_CRC;
        }
        break;
    case RCV_PAYLOAD:
        s_rcv.buf[12 + s_rcv.idx++] = byte;
        if (s_rcv.idx >= s_rcv.payload_len) {
            s_rcv.idx = 0;  /* 重置给 RCV_CRC 使用 */
            s_rcv.state = RCV_CRC;
        }
        break;
    case RCV_CRC:
        s_rcv.buf[12 + s_rcv.payload_len + s_rcv.idx++] = byte;
        if (s_rcv.idx >= 2) {
            uint16_t total = 12 + s_rcv.payload_len + 2;
            process_frame(s_rcv.buf, total);
            s_rcv.state = RCV_SOF0;
        }
        break;
    }
}

/* ====== SysTick 采样执行 ====== */
void debug_monitor_on_tick(void) {
    static uint32_t s_tick_us = 0;
    s_tick_us += 1000; /* 假设 1ms tick */

    for (int i = 0; i < DM_MAX_LISTS; i++) {
        dm_sample_list_t* L = &s_lists[i];
        if (!L->enabled || L->count == 0) continue;
        if (s_tick_us - L->last_tick < (uint32_t)L->period_us) continue;
        L->last_tick = s_tick_us;

        /* 采集所有变量 */
        uint16_t offset = 0;
        for (int j = 0; j < L->count; j++) {
            dm_sample_item_t* it = &L->items[j];
            memcpy(s_stream_buf + offset, dm_resolve(it->address), it->size);
            offset += it->size;
        }

        /* 构建流式帧并发送 */
        uint8_t hdr[12];
        hdr[0]=DM_SOF0; hdr[1]=DM_SOF1; hdr[2]=0x01; hdr[3]=DM_CMD_STREAM_DATA;
        L->seq++;
        put_u16_le(hdr+4, L->seq);
        uint32_t ts = dbg_get_timestamp_us();
        put_u32_le(hdr+6, ts);
        hdr[10] = (uint8_t)i;
        hdr[11] = 1; /* sample_count */

        uint16_t crc = dm_crc16(hdr, 12);
        crc = dm_crc16_continue(crc, s_stream_buf, offset);

        dbg_uart_send(hdr, 12);
        dbg_uart_send(s_stream_buf, offset);
        uint8_t crcl[2] = { (uint8_t)(crc&0xFF), (uint8_t)(crc>>8) };
        dbg_uart_send(crcl, 2);
        s_stats.stream_frames_sent++;
    }
}

/* ====== 初始化 ====== */
void debug_monitor_init(void) {
    memset(&s_rcv, 0, sizeof(s_rcv));
    memset(s_lists, 0, sizeof(s_lists));
    memset(&s_stats, 0, sizeof(s_stats));
    s_rcv.state = RCV_SOF0;
}
