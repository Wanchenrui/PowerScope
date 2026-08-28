/**
 * ring_buffer.h — 无锁环形缓冲区接口（单生产者单消费者）
 *
 * 适用于串口接收回调(生产者) → 协议解析(消费者) 场景。
 * write_pos 仅生产者修改，read_pos 仅消费者修改，
 * 两者对 32 位对齐变量的读写在各主流架构上原子。
 */
#ifndef RING_BUFFER_H
#define RING_BUFFER_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ring_buffer ring_buffer_t;

/**
 * 创建环形缓冲区
 * @param capacity 缓冲区容量(字节)，建议 2 的幂以优化取模
 * @return 缓冲区指针，NULL=失败
 */
ring_buffer_t* ring_buffer_create(uint32_t capacity);

/**
 * 销毁环形缓冲区，释放内存
 */
void ring_buffer_destroy(ring_buffer_t* rb);

/**
 * 写入数据(生产者调用)
 * @param rb   缓冲区
 * @param data 数据指针
 * @param len  期望写入长度
 * @return 实际写入长度(可能小于 len，缓冲区满时丢弃超出部分)
 */
uint32_t ring_buffer_write(ring_buffer_t* rb, const uint8_t* data, uint32_t len);

/**
 * 读取数据(消费者调用)
 * @param rb   缓冲区
 * @param buf  输出缓冲区
 * @param len  期望读取长度
 * @return 实际读取长度
 */
uint32_t ring_buffer_read(ring_buffer_t* rb, uint8_t* buf, uint32_t len);

/**
 * 偷看数据(不移动读指针)
 * @return 实际偷看长度
 */
uint32_t ring_buffer_peek(ring_buffer_t* rb, uint8_t* buf, uint32_t len);

/**
 * 获取可读数据量
 */
uint32_t ring_buffer_available(ring_buffer_t* rb);

/**
 * 获取剩余可写空间
 */
uint32_t ring_buffer_free_space(ring_buffer_t* rb);

/**
 * 清空缓冲区
 */
void ring_buffer_clear(ring_buffer_t* rb);

/**
 * 获取容量
 */
uint32_t ring_buffer_capacity(ring_buffer_t* rb);

#ifdef __cplusplus
}
#endif
#endif /* RING_BUFFER_H */
