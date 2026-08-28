/**
 * crc16_table.h — CRC16-Modbus 查表法接口
 *
 * 多项式: 0xA001 (反射的 0x8005)
 * 初始值: 0xFFFF
 * 输入/输出反射: 是
 * 异或输出: 0x0000
 *
 * 典型用于 Modbus RTU 帧校验。
 */
#ifndef CRC16_TABLE_H
#define CRC16_TABLE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 计算 CRC16-Modbus（查表法，O(n) 每字节一次查表+异或）
 * @param data 数据指针
 * @param len  数据长度
 * @return CRC16 值
 */
uint16_t crc16_modbus(const uint8_t* data, uint32_t len);

/**
 * 续算 CRC16（用于分片数据的 CRC 计算）
 * @param crc     上一次的 CRC 值（首次传 0xFFFF）
 * @param data    数据指针
 * @param len     数据长度
 * @return 更新后的 CRC 值
 */
uint16_t crc16_modbus_continue(uint16_t crc, const uint8_t* data, uint32_t len);

/**
 * 逐位计算 CRC16-Modbus（不查表，用于验证查表法正确性）
 * @param data 数据指针
 * @param len  数据长度
 * @return CRC16 值
 */
uint16_t crc16_modbus_bitwise(const uint8_t* data, uint32_t len);

#ifdef __cplusplus
}
#endif
#endif /* CRC16_TABLE_H */
