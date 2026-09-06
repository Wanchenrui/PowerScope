#ifndef TEST_DEVICE_H
#define TEST_DEVICE_H
#include <stdint.h>
typedef float float32_t;
struct TestDwt { uint32_t CYCCNT; };
extern struct TestDwt test_dwt;
#define DWT (&test_dwt)
#define __DMB() __asm__ volatile ("" ::: "memory")
#endif
