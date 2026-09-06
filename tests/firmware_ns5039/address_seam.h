#include <stdint.h>
void *ns5039_test_pointer(uint32_t address);
#define DM_MEMORY_POINTER(address) ns5039_test_pointer(address)
