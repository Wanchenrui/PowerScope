/**
 * power_core.h — PowerScope C 核心库公共头文件
 *
 * 统一包含所有子模块头文件，定义通用类型和宏。
 * CFFI 通过读取此文件生成 Python 绑定。
 */
#ifndef POWER_CORE_H
#define POWER_CORE_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ====== 库版本 ====== */
#define POWER_CORE_VERSION_MAJOR  0
#define POWER_CORE_VERSION_MINOR  1
#define POWER_CORE_VERSION_PATCH  0
#define POWER_CORE_VERSION        ((0 << 16) | (1 << 8) | 0)

/* ====== 通用返回码 ====== */
#define PC_OK              0
#define PC_ERR_GENERIC    -1
#define PC_ERR_PARAM      -2
#define PC_ERR_NOMEM      -3
#define PC_ERR_OVERFLOW   -4
#define PC_ERR_TIMEOUT    -5
#define PC_ERR_NOT_FOUND  -6
#define PC_ERR_BUSY       -7

/* ====== 子模块包含 ====== */
#include "crc16_table.h"
#include "ring_buffer.h"

/* 获取库版本字符串 */
const char* pc_get_version(void);

#ifdef __cplusplus
}
#endif
#endif /* POWER_CORE_H */
