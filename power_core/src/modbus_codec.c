/**
 * modbus_codec.c — Modbus RTU 帧编解码实现
 */
#include "modbus_codec.h"
#include "crc16_table.h"
#include <string.h>

#define EXPORT __declspec(dllexport)

/* 大端写入 16 位值 (Modbus 地址/数量/寄存器值使用大端序) */
static inline void put_u16_be(uint8_t* p, uint16_t v) {
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)(v & 0xFF);
}

/* 大端读取 16 位值 */
static inline uint16_t get_u16_be(const uint8_t* p) {
    return ((uint16_t)p[0] << 8) | (uint16_t)p[1];
}

/* 小端读取 16 位值 (仅 CRC 使用小端序) */
static inline uint16_t get_u16_le(const uint8_t* p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

/* 追加 CRC 到帧尾 (小端) */
static int32_t append_crc(uint8_t* buf, uint32_t payload_len, uint32_t buf_size) {
    if (payload_len + 2 > buf_size) return MB_ERR_SHORT;
    uint16_t crc = crc16_modbus(buf, payload_len);
    buf[payload_len]     = (uint8_t)(crc & 0xFF);
    buf[payload_len + 1] = (uint8_t)(crc >> 8);
    return (int32_t)(payload_len + 2);
}

EXPORT int32_t modbus_build_read_holding(uint8_t* buf, uint32_t buf_size,
                                   uint8_t slave_id,
                                   uint16_t start_addr, uint16_t reg_count) {
    if (!buf || buf_size < 8) return MB_ERR_SHORT;
    if (reg_count == 0 || reg_count > 125) return MB_ERR_LEN;
    buf[0] = slave_id;
    buf[1] = MB_FC_READ_HOLDING;
    put_u16_be(buf + 2, start_addr);
    put_u16_be(buf + 4, reg_count);
    return append_crc(buf, 6, buf_size);
}

EXPORT int32_t modbus_build_write_single(uint8_t* buf, uint32_t buf_size,
                                   uint8_t slave_id,
                                   uint16_t addr, uint16_t value) {
    if (!buf || buf_size < 8) return MB_ERR_SHORT;
    buf[0] = slave_id;
    buf[1] = MB_FC_WRITE_SINGLE_REG;
    put_u16_be(buf + 2, addr);
    put_u16_be(buf + 4, value);
    return append_crc(buf, 6, buf_size);
}

EXPORT int32_t modbus_build_write_multi(uint8_t* buf, uint32_t buf_size,
                                  uint8_t slave_id,
                                  uint16_t start_addr,
                                  const uint16_t* regs, uint16_t reg_count) {
    if (!buf || !regs) return MB_ERR_SHORT;
    if (reg_count == 0 || reg_count > 123) return MB_ERR_LEN;
    uint32_t payload = 7 + (uint32_t)reg_count * 2;
    if (buf_size < payload + 2) return MB_ERR_SHORT;

    buf[0] = slave_id;
    buf[1] = MB_FC_WRITE_MULTI_REG;
    put_u16_be(buf + 2, start_addr);
    put_u16_be(buf + 4, reg_count);
    buf[6] = (uint8_t)(reg_count * 2);
    for (uint16_t i = 0; i < reg_count; i++) {
        put_u16_be(buf + 7 + i * 2, regs[i]);
    }
    return append_crc(buf, payload, buf_size);
}

EXPORT int32_t modbus_build_read_holding_response(uint8_t* buf, uint32_t buf_size,
                                            uint8_t slave_id,
                                            const uint16_t* regs, uint16_t reg_count) {
    if (!buf || !regs) return MB_ERR_SHORT;
    if (reg_count == 0 || reg_count > 125) return MB_ERR_LEN;
    uint32_t payload = 3 + (uint32_t)reg_count * 2;
    if (buf_size < payload + 2) return MB_ERR_SHORT;

    buf[0] = slave_id;
    buf[1] = MB_FC_READ_HOLDING;
    buf[2] = (uint8_t)(reg_count * 2);
    for (uint16_t i = 0; i < reg_count; i++) {
        put_u16_be(buf + 3 + i * 2, regs[i]);
    }
    return append_crc(buf, payload, buf_size);
}

EXPORT int32_t modbus_parse_rtu_response(const uint8_t* data, uint32_t len,
                                   const modbus_request_t* req,
                                   modbus_response_t* resp) {
    if (!data || !resp) return MB_ERR_SHORT;
    memset(resp, 0, sizeof(*resp));

    /* 最小帧长: slave(1) + fc(1) + crc(2) = 4 */
    if (len < 4) return MB_ERR_SHORT;

    /* CRC 校验 */
    uint16_t crc_calc = crc16_modbus(data, len - 2);
    uint16_t crc_recv = get_u16_le(data + len - 2);
    if (crc_calc != crc_recv) return MB_ERR_CRC;

    uint8_t slave_id = data[0];
    uint8_t fc = data[1];

    /* 校验从站地址 */
    if (req && req->slave_id != slave_id) return MB_ERR_ADDR;

    /* 异常响应 (功能码最高位=1) */
    if (fc & 0x80) {
        if (len < 5) return MB_ERR_SHORT;
        resp->slave_id = slave_id;
        resp->function_code = fc;
        resp->is_exception = true;
        resp->exception_code = data[2];
        return MB_ERR_EXCEPT;
    }

    /* 校验功能码 */
    if (req && req->function_code != fc) return MB_ERR_FC;
    resp->slave_id = slave_id;
    resp->function_code = fc;

    switch (fc) {
    case MB_FC_READ_HOLDING:
    case MB_FC_READ_INPUT: {
        if (len < 5) return MB_ERR_SHORT;
        resp->byte_count = data[2];
        uint16_t expected_regs = resp->byte_count / 2;
        /* 校验: 3 + byte_count + 2 == len */
        if (3 + resp->byte_count + 2 != len) return MB_ERR_LEN;
        if (req && req->reg_count != expected_regs) return MB_ERR_LEN;
        resp->reg_count = (uint8_t)expected_regs;
        for (uint16_t i = 0; i < expected_regs && i < 256; i++) {
            resp->registers[i] = get_u16_be(data + 3 + i * 2);
        }
        break;
    }
    case MB_FC_WRITE_SINGLE:
    case MB_FC_WRITE_SINGLE_REG: {
        if (len < 8) return MB_ERR_SHORT;
        resp->written_addr = get_u16_be(data + 2);
        resp->written_count = get_u16_be(data + 4); /* 对 FC=06 是写入值 */
        break;
    }
    case MB_FC_WRITE_MULTI_REG: {
        if (len < 8) return MB_ERR_SHORT;
        resp->written_addr = get_u16_be(data + 2);
        resp->written_count = get_u16_be(data + 4);
        break;
    }
    default:
        /* 其他功能码: 原样保留 */
        break;
    }

    return MB_OK;
}

EXPORT int32_t modbus_rtu_expected_len(const uint8_t* data, uint32_t len) {
    if (!data || len < 2) return 0;
    uint8_t fc = data[1];

    /* 异常响应: slave(1) + fc(1) + exc(1) + crc(2) = 5 */
    if (fc & 0x80) return 5;

    switch (fc) {
    case MB_FC_READ_COILS:
    case MB_FC_READ_DISCRETE:
    case MB_FC_READ_HOLDING:
    case MB_FC_READ_INPUT:
        /* 需要第3字节(byte_count)才能确定: slave+fc+bc+data+crc */
        if (len < 3) return 0; /* 数据不足 */
        return 3 + data[2] + 2;

    case MB_FC_WRITE_SINGLE:      /* 线圈 */
    case MB_FC_WRITE_SINGLE_REG:  /* 寄存器 */
        return 8; /* slave+fc+addr(2)+value(2)+crc(2) */

    case MB_FC_WRITE_MULTI:
    case MB_FC_WRITE_MULTI_REG:
        return 8; /* slave+fc+addr(2)+count(2)+crc(2) */

    default:
        return 0; /* 未知功能码, 无法判断 */
    }
}
