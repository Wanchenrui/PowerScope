/**
 * debug_protocol.c — MCU 调试协议引擎实现
 *
 * 帧编解码: SOF(2) + VER(1) + CMD(1) + SEQ(2) + ADDR(4) + LEN(2) + PAYLOAD(N) + CRC16(2)
 * 小端序: SEQ/ADDR/LEN (与 ARM Cortex-M 一致)
 * CRC16: Modbus, 小端序
 */
#include "debug_protocol.h"
#include "crc16_table.h"
#include <string.h>

#define EXPORT __declspec(dllexport)

/* 小端写入/读取 (帧内字段) */
static inline void put_u16_le(uint8_t* p, uint16_t v) {
    p[0] = (uint8_t)(v & 0xFF); p[1] = (uint8_t)(v >> 8);
}
static inline void put_u32_le(uint8_t* p, uint32_t v) {
    p[0] = (uint8_t)(v & 0xFF); p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static inline uint16_t get_u16_le(const uint8_t* p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}
static inline uint32_t get_u32_le(const uint8_t* p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

EXPORT int32_t dbg_build_frame(uint8_t* buf, uint32_t buf_size,
                        uint8_t cmd, uint16_t seq, uint32_t address,
                        const uint8_t* payload, uint16_t payload_len) {
    if (!buf) return -1;
    uint32_t total = DBG_HDR_SIZE + payload_len + DBG_CRC_SIZE;
    if (buf_size < total) return -2;
    if (payload_len > 0 && !payload) return -1;

    buf[0] = DBG_SOF0;
    buf[1] = DBG_SOF1;
    buf[2] = DBG_PROTOCOL_VER;
    buf[3] = cmd;
    put_u16_le(buf + 4, seq);
    put_u32_le(buf + 6, address);
    put_u16_le(buf + 10, payload_len);
    if (payload_len > 0) {
        memcpy(buf + DBG_HDR_SIZE, payload, payload_len);
    }
    uint16_t crc = crc16_modbus(buf, DBG_HDR_SIZE + payload_len);
    put_u16_le(buf + DBG_HDR_SIZE + payload_len, crc);
    return (int32_t)total;
}

EXPORT int32_t dbg_parse_frame(const uint8_t* data, uint32_t len, dbg_frame_t* frame) {
    if (!data || !frame) return DBG_ST_ERR_CMD;
    if (len < DBG_HDR_SIZE + DBG_CRC_SIZE) return DBG_ST_ERR_LEN;

    /* 帧头校验 */
    if (data[0] != DBG_SOF0 || data[1] != DBG_SOF1) return DBG_ST_ERR_CMD;

    /* CRC 校验 */
    uint16_t payload_len = get_u16_le(data + 10);
    uint32_t expected_total = DBG_HDR_SIZE + payload_len + DBG_CRC_SIZE;
    if (len < expected_total) return DBG_ST_ERR_LEN;

    uint16_t crc_calc = crc16_modbus(data, DBG_HDR_SIZE + payload_len);
    uint16_t crc_recv = get_u16_le(data + DBG_HDR_SIZE + payload_len);
    if (crc_calc != crc_recv) return DBG_ST_ERR_CRC;

    frame->version = data[2];
    frame->cmd = data[3];
    frame->seq = get_u16_le(data + 4);
    frame->address = get_u32_le(data + 6);
    frame->length = payload_len;
    frame->payload = data + DBG_HDR_SIZE;
    frame->payload_len = payload_len;
    return DBG_ST_OK;
}

EXPORT int32_t dbg_build_response(uint8_t* buf, uint32_t buf_size,
                           uint8_t cmd, uint16_t seq, uint8_t status,
                           const uint8_t* payload, uint16_t payload_len) {
    if (!buf) return -1;
    /* 响应帧: SOF(2)+VER(1)+CMD(1)+SEQ(2)+STATUS(1)+LEN(2)+PAYLOAD+CRC(2) = 9+payload+2 */
    uint32_t total = 9 + payload_len + DBG_CRC_SIZE;
    if (buf_size < total) return -2;

    buf[0] = DBG_SOF0;
    buf[1] = DBG_SOF1;
    buf[2] = DBG_PROTOCOL_VER;
    buf[3] = cmd;
    put_u16_le(buf + 4, seq);
    buf[6] = status;
    put_u16_le(buf + 7, payload_len);
    if (payload_len > 0 && payload) {
        memcpy(buf + 9, payload, payload_len);
    }
    uint16_t crc = crc16_modbus(buf, 9 + payload_len);
    put_u16_le(buf + 9 + payload_len, crc);
    return (int32_t)total;
}

EXPORT int32_t dbg_build_stream_frame(uint8_t* buf, uint32_t buf_size,
                               uint16_t seq, uint32_t timestamp,
                               uint8_t list_id, uint8_t sample_count,
                               const uint8_t* data, uint16_t data_len) {
    if (!buf) return -1;
    /* 流式帧: SOF(2)+VER(1)+CMD(1)+SEQ(2)+TS(4)+LIST_ID(1)+COUNT(1)+DATA+CRC(2) = 12+data+2 */
    uint32_t total = 12 + data_len + DBG_CRC_SIZE;
    if (buf_size < total) return -2;

    buf[0] = DBG_SOF0;
    buf[1] = DBG_SOF1;
    buf[2] = DBG_PROTOCOL_VER;
    buf[3] = DBG_CMD_STREAM_DATA;
    put_u16_le(buf + 4, seq);
    put_u32_le(buf + 6, timestamp);
    buf[10] = list_id;
    buf[11] = sample_count;
    if (data_len > 0 && data) {
        memcpy(buf + 12, data, data_len);
    }
    uint16_t crc = crc16_modbus(buf, 12 + data_len);
    put_u16_le(buf + 12 + data_len, crc);
    return (int32_t)total;
}

EXPORT int32_t dbg_parse_stream_frame(const uint8_t* data, uint32_t len,
                               uint16_t* seq, uint32_t* timestamp,
                               uint8_t* list_id, uint8_t* sample_count,
                               const uint8_t** payload, uint16_t* payload_len) {
    if (!data || !seq || !timestamp || !list_id || !sample_count || !payload || !payload_len)
        return DBG_ST_ERR_CMD;
    if (len < 12 + DBG_CRC_SIZE) return DBG_ST_ERR_LEN;

    if (data[0] != DBG_SOF0 || data[1] != DBG_SOF1) return DBG_ST_ERR_CMD;
    if (data[3] != DBG_CMD_STREAM_DATA) return DBG_ST_ERR_CMD;

    /* 流式帧没有显式 LEN 字段, 长度 = 总长 - 12 - 2(CRC) */
    uint16_t plen = (uint16_t)(len - 12 - DBG_CRC_SIZE);

    /* CRC 校验 */
    uint16_t crc_calc = crc16_modbus(data, 12 + plen);
    uint16_t crc_recv = get_u16_le(data + 12 + plen);
    if (crc_calc != crc_recv) return DBG_ST_ERR_CRC;

    *seq = get_u16_le(data + 4);
    *timestamp = get_u32_le(data + 6);
    *list_id = data[10];
    *sample_count = data[11];
    *payload = data + 12;
    *payload_len = plen;
    return DBG_ST_OK;
}

EXPORT uint32_t dbg_expected_frame_len(const uint8_t* data, uint32_t len) {
    if (!data || len < DBG_HDR_SIZE) return 0;
    if (data[0] != DBG_SOF0 || data[1] != DBG_SOF1) return 0;
    uint16_t payload_len = get_u16_le(data + 10);
    return DBG_HDR_SIZE + payload_len + DBG_CRC_SIZE;
}
