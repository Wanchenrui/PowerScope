/**
 * ring_buffer.c — 无锁环形缓冲区实现（单生产者单消费者）
 */
#include "ring_buffer.h"
#include <stdlib.h>
#include <string.h>

struct ring_buffer {
    uint8_t*          buffer;
    uint32_t          capacity;
    uint32_t          mask;       /* capacity 为 2 的幂时 mask=capacity-1, 否则 0 */
    volatile uint32_t write_pos;  /* 生产者修改 */
    volatile uint32_t read_pos;   /* 消费者修改 */
};

/* 判断是否为 2 的幂 */
static bool is_power_of_two(uint32_t n) {
    return n > 0 && (n & (n - 1)) == 0;
}

__declspec(dllexport) ring_buffer_t* ring_buffer_create(uint32_t capacity) {
    if (capacity == 0) return NULL;
    ring_buffer_t* rb = (ring_buffer_t*)malloc(sizeof(ring_buffer_t));
    if (!rb) return NULL;
    rb->buffer = (uint8_t*)malloc(capacity);
    if (!rb->buffer) { free(rb); return NULL; }
    rb->capacity = capacity;
    rb->mask = is_power_of_two(capacity) ? (capacity - 1) : 0;
    rb->write_pos = 0;
    rb->read_pos = 0;
    return rb;
}

__declspec(dllexport) void ring_buffer_destroy(ring_buffer_t* rb) {
    if (!rb) return;
    free(rb->buffer);
    free(rb);
}

static inline uint32_t idx_of(ring_buffer_t* rb, uint32_t pos) {
    /* 2 的幂容量用位与(更快)，否则用取模 */
    return rb->mask ? (pos & rb->mask) : (pos % rb->capacity);
}

__declspec(dllexport) uint32_t ring_buffer_write(ring_buffer_t* rb, const uint8_t* data, uint32_t len) {
    if (!rb || !data) return 0;
    uint32_t wp = rb->write_pos;
    uint32_t rp = rb->read_pos;
    uint32_t free_space = rb->capacity - (wp - rp); /* 无符号回绕安全 */
    if (len > free_space) len = free_space;          /* 满则丢弃超出 */

    /* 分两段拷贝(可能回绕) */
    uint32_t start = idx_of(rb, wp);
    uint32_t first = rb->capacity - start;
    if (first > len) first = len;
    memcpy(rb->buffer + start, data, first);
    if (len > first) {
        memcpy(rb->buffer, data + first, len - first);
    }
    rb->write_pos = wp + len; /* 内存屏障: x86 强序天然安全; ARM 需确保 store 顺序 */
    return len;
}

__declspec(dllexport) uint32_t ring_buffer_read(ring_buffer_t* rb, uint8_t* buf, uint32_t len) {
    if (!rb || !buf) return 0;
    uint32_t rp = rb->read_pos;
    uint32_t wp = rb->write_pos;
    uint32_t available = wp - rp; /* 无符号回绕安全 */
    if (len > available) len = available;

    uint32_t start = idx_of(rb, rp);
    uint32_t first = rb->capacity - start;
    if (first > len) first = len;
    memcpy(buf, rb->buffer + start, first);
    if (len > first) {
        memcpy(buf + first, rb->buffer, len - first);
    }
    rb->read_pos = rp + len;
    return len;
}

__declspec(dllexport) uint32_t ring_buffer_peek(ring_buffer_t* rb, uint8_t* buf, uint32_t len) {
    if (!rb || !buf) return 0;
    uint32_t rp = rb->read_pos;
    uint32_t wp = rb->write_pos;
    uint32_t available = wp - rp;
    if (len > available) len = available;

    uint32_t start = idx_of(rb, rp);
    uint32_t first = rb->capacity - start;
    if (first > len) first = len;
    memcpy(buf, rb->buffer + start, first);
    if (len > first) {
        memcpy(buf + first, rb->buffer, len - first);
    }
    /* 不移动 read_pos */
    return len;
}

__declspec(dllexport) uint32_t ring_buffer_available(ring_buffer_t* rb) {
    if (!rb) return 0;
    return rb->write_pos - rb->read_pos;
}

__declspec(dllexport) uint32_t ring_buffer_free_space(ring_buffer_t* rb) {
    if (!rb) return 0;
    return rb->capacity - (rb->write_pos - rb->read_pos);
}

__declspec(dllexport) void ring_buffer_clear(ring_buffer_t* rb) {
    if (!rb) return;
    rb->write_pos = 0;
    rb->read_pos = 0;
}

__declspec(dllexport) uint32_t ring_buffer_capacity(ring_buffer_t* rb) {
    return rb ? rb->capacity : 0;
}
