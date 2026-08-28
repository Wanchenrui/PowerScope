/**
 * debug_protocol.h — MCU 调试协议引擎接口
 *
 * 帧格式: SOF(0xA5 0x5A) + VER + CMD + SEQ(2) + ADDR(4) + LEN(2) + PAYLOAD + CRC16(2)
 * 多字节字段(SEQ/ADDR/LEN): 小端序 (与 ARM Cortex-M 一致)
 * CRC16: Modbus, 小端序
 *
 * 命令码:
 *   0x01 READ_MEM       读内存
 *   0x02 WRITE_MEM      写内存
 *   0x03 READ_BATCH     批量读
 *   0x04 SET_SAMPLE     配置采样列表
 *   0x05 START_STREAM   启动流式上报
 *   0x06 STOP_STREAM    停止流式上报
 *   0x07 GET_INFO       获取设备信息
 *   0x08 SET_PARAM      设置参数(带安全校验)
 *   0x09 TRIGGER_STEP   触发阶跃响应
 *   0x0A RESET          软复位
 *   0x10 STREAM_DATA    流式数据上报(MCU→PC)
 *   0xFF NACK           错误响应
 */
#ifndef DEBUG_PROTOCOL_H
#define DEBUG_PROTOCOL_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ====== 帧常量 ====== */
#define DBG_SOF0             0xA5
#define DBG_SOF1             0x5A
#define DBG_PROTOCOL_VER     0x01
#define DBG_HDR_SIZE         12   /* SOF(2)+VER(1)+CMD(1)+SEQ(2)+ADDR(4)+LEN(2) */
#define DBG_CRC_SIZE         2
#define DBG_MAX_PAYLOAD      512

/* ====== 命令码 ====== */
#define DBG_CMD_READ_MEM      0x01
#define DBG_CMD_WRITE_MEM     0x02
#define DBG_CMD_READ_BATCH    0x03
#define DBG_CMD_SET_SAMPLE    0x04
#define DBG_CMD_START_STREAM  0x05
#define DBG_CMD_STOP_STREAM   0x06
#define DBG_CMD_GET_INFO      0x07
#define DBG_CMD_SET_PARAM     0x08
#define DBG_CMD_TRIGGER_STEP  0x09
#define DBG_CMD_RESET         0x0A
#define DBG_CMD_STREAM_DATA   0x10
#define DBG_CMD_NACK          0xFF

/* ====== 状态码 ====== */
#define DBG_ST_OK             0x00
#define DBG_ST_ERR_CRC        0x01
#define DBG_ST_ERR_CMD        0x02
#define DBG_ST_ERR_ADDR       0x03
#define DBG_ST_ERR_LEN        0x04
#define DBG_ST_ERR_BUSY       0x05
#define DBG_ST_ERR_PROTECTED  0x06
#define DBG_ST_ERR_LIST_FULL  0x07

/* ====== 帧结构 ====== */
typedef struct {
    uint8_t  version;
    uint8_t  cmd;
    uint16_t seq;
    uint32_t address;
    uint16_t length;
    const uint8_t* payload;   /* 指向帧内 payload, 不拥有内存 */
    uint16_t payload_len;
} dbg_frame_t;

/* ====== 帧构建 (PC→MCU) ====== */

/**
 * 构建命令帧
 * @param buf       输出缓冲区
 * @param buf_size  缓冲区大小
 * @param cmd       命令码
 * @param seq       序列号
 * @param address   地址 (读/写命令使用, 其他填0)
 * @param payload   负载数据 (可为 NULL)
 * @param payload_len 负载长度
 * @return 帧总长度, <0=错误
 */
int32_t dbg_build_frame(uint8_t* buf, uint32_t buf_size,
                        uint8_t cmd, uint16_t seq, uint32_t address,
                        const uint8_t* payload, uint16_t payload_len);

/* ====== 帧解析 ====== */

/**
 * 解析帧
 * @param data  帧数据
 * @param len   数据长度
 * @param frame 输出解析结果
 * @return DBG_ST_OK 或错误码
 */
int32_t dbg_parse_frame(const uint8_t* data, uint32_t len, dbg_frame_t* frame);

/**
 * 构建响应帧
 * @param cmd      原命令码
 * @param seq      原序列号
 * @param status   状态码
 * @param payload  响应数据
 * @param payload_len 响应数据长度
 * @return 帧总长度, <0=错误
 */
int32_t dbg_build_response(uint8_t* buf, uint32_t buf_size,
                           uint8_t cmd, uint16_t seq, uint8_t status,
                           const uint8_t* payload, uint16_t payload_len);

/**
 * 构建流式数据帧 (MCU→PC 主动推送)
 * @param seq          采样序列号
 * @param timestamp    MCU 时间戳
 * @param list_id      采样列表 ID
 * @param sample_count 采样点数
 * @param data         采样数据
 * @param data_len     数据长度
 * @return 帧总长度, <0=错误
 */
int32_t dbg_build_stream_frame(uint8_t* buf, uint32_t buf_size,
                               uint16_t seq, uint32_t timestamp,
                               uint8_t list_id, uint8_t sample_count,
                               const uint8_t* data, uint16_t data_len);

/**
 * 解析流式数据帧
 * @param data          帧数据
 * @param len           数据长度
 * @param seq           输出: 采样序列号
 * @param timestamp     输出: 时间戳
 * @param list_id       输出: 列表 ID
 * @param sample_count  输出: 采样点数
 * @param payload       输出: 数据指针(帧内, 不拷贝)
 * @param payload_len   输出: 数据长度
 * @return DBG_ST_OK 或错误码
 */
int32_t dbg_parse_stream_frame(const uint8_t* data, uint32_t len,
                               uint16_t* seq, uint32_t* timestamp,
                               uint8_t* list_id, uint8_t* sample_count,
                               const uint8_t** payload, uint16_t* payload_len);

/**
 * 获取帧的期望总长度 (用于接收状态机判断帧完整性)
 * @param data  已接收数据 (至少 DBG_HDR_SIZE 字节)
 * @param len   已接收长度
 * @return 期望帧总长度, 0=数据不足
 */
uint32_t dbg_expected_frame_len(const uint8_t* data, uint32_t len);

/* ====== 采样列表项 ====== */
typedef struct {
    uint32_t address;
    uint8_t  size;     /* 1/2/4/8 */
    uint8_t  reserved;
} dbg_sample_item_t;

#ifdef __cplusplus
}
#endif
#endif /* DEBUG_PROTOCOL_H */
