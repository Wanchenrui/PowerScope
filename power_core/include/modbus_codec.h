/**
 * modbus_codec.h — Modbus RTU/TCP 帧编解码接口
 *
 * C 负责帧级编解码热路径 (高频, 微秒级延迟敏感)。
 * Python 负责语义解析 (寄存器→物理量映射)。
 */
#ifndef MODBUS_CODEC_H
#define MODBUS_CODEC_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ====== Modbus 功能码 ====== */
#define MB_FC_READ_COILS          0x01
#define MB_FC_READ_DISCRETE       0x02
#define MB_FC_READ_HOLDING        0x03
#define MB_FC_READ_INPUT          0x04
#define MB_FC_WRITE_SINGLE        0x05  /* 线圈 */
#define MB_FC_WRITE_SINGLE_REG    0x06
#define MB_FC_WRITE_MULTI         0x0F
#define MB_FC_WRITE_MULTI_REG     0x10
#define MB_FC_MASK_WRITE_REG      0x16
#define MB_FC_RW_MULTI_REG        0x17

/* ====== 错误码 ====== */
#define MB_OK                 0
#define MB_ERR_CRC           -1
#define MB_ERR_SHORT         -2   /* 帧太短 */
#define MB_ERR_FC            -3   /* 功能码不匹配 */
#define MB_ERR_ADDR          -4   /* 从站地址不匹配 */
#define MB_ERR_LEN           -5   /* 数据长度不匹配 */
#define MB_ERR_EXCEPT        -6   /* 异常响应 */

/* Modbus 异常码 */
#define MB_EXC_ILLEGAL_FUNC    0x01
#define MB_EXC_ILLEGAL_ADDR    0x02
#define MB_EXC_ILLEGAL_VALUE   0x03
#define MB_EXC_SLAVE_FAILURE   0x04

/* ====== 请求结构 ====== */
typedef struct {
    uint8_t  slave_id;
    uint8_t  function_code;
    uint16_t start_addr;   /* 0-based */
    uint16_t reg_count;
    uint16_t write_value;  /* FC=06/05: 写入值 */
} modbus_request_t;

/* ====== 响应结构 ====== */
typedef struct {
    uint8_t  slave_id;
    uint8_t  function_code;
    uint8_t  byte_count;        /* 读响应: 数据字节数 */
    uint16_t registers[256];    /* 读响应: 寄存器数据 */
    uint8_t  reg_count;         /* 读响应: 寄存器个数 */
    uint16_t written_addr;      /* 写响应: 写入地址 */
    uint16_t written_count;     /* 写响应: 写入数量 */
    uint8_t  exception_code;    /* 异常响应: 异常码 */
    bool     is_exception;      /* 是否异常响应 */
} modbus_response_t;

/* ====== RTU 帧编解码 ====== */

/**
 * 构建 Modbus RTU 读保持寄存器请求帧 (FC=03)
 * @param buf       输出缓冲区 (至少 8 字节)
 * @param buf_size  缓冲区大小
 * @param slave_id  从站地址
 * @param start_addr 起始地址 (0-based)
 * @param reg_count  寄存器数量
 * @return 帧总长度 (含CRC), <0=错误
 */
int32_t modbus_build_read_holding(uint8_t* buf, uint32_t buf_size,
                                   uint8_t slave_id,
                                   uint16_t start_addr, uint16_t reg_count);

/**
 * 构建 Modbus RTU 写单个寄存器请求帧 (FC=06)
 */
int32_t modbus_build_write_single(uint8_t* buf, uint32_t buf_size,
                                   uint8_t slave_id,
                                   uint16_t addr, uint16_t value);

/**
 * 构建 Modbus RTU 写多个寄存器请求帧 (FC=10)
 * @param regs       寄存器值数组
 * @param reg_count  寄存器数量
 */
int32_t modbus_build_write_multi(uint8_t* buf, uint32_t buf_size,
                                  uint8_t slave_id,
                                  uint16_t start_addr,
                                  const uint16_t* regs, uint16_t reg_count);

/**
 * 解析 Modbus RTU 响应帧
 * @param data       响应数据
 * @param len        数据长度
 * @param req        对应的请求 (用于校验从站/功能码), 可为 NULL
 * @param resp       输出解析结果
 * @return MB_OK 或错误码
 */
int32_t modbus_parse_rtu_response(const uint8_t* data, uint32_t len,
                                   const modbus_request_t* req,
                                   modbus_response_t* resp);

/**
 * 构建 Modbus RTU 读保持寄存器响应帧 (FC=03) — 用于从站仿真
 */
int32_t modbus_build_read_holding_response(uint8_t* buf, uint32_t buf_size,
                                            uint8_t slave_id,
                                            const uint16_t* regs, uint16_t reg_count);

/**
 * 计算完整 RTU 帧的最小长度判断
 * 根据功能码和数据内容判断期望帧长 (用于接收状态机判断帧是否完整)
 * @param data  已接收数据 (至少 2 字节: slave_id + fc)
 * @param len   已接收长度
 * @return 期望帧总长度, 0=数据不足无法判断, <0=错误
 */
int32_t modbus_rtu_expected_len(const uint8_t* data, uint32_t len);

#ifdef __cplusplus
}
#endif
#endif /* MODBUS_CODEC_H */
