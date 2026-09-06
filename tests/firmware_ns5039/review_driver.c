/* Independent review driver: raw caller frames into the production dispatcher.
 * Hardware-only seams; no implementation test oracle is imported. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "debug_monitor_core.c"
InvCurrLoopCfg g_invCurrLoopCfg;
InvVoltLoopCfg g_invVoltLoopCfg;
UrmsLoopCfg g_uRmsLoopCfg;
struct TestDwt test_dwt;
#include "t09_review_state.h"
static union { uint64_t alignment; uint8_t bytes[0x80000]; } ram;
static uint8_t response[256];
static uint16_t response_len;
void *ns5039_test_pointer(uint32_t address) {
    if(address == (uint32_t)(uintptr_t)&g_invVoltLoopCfg.voltCfg.kp) return &g_invVoltLoopCfg.voltCfg.kp;
    if(address == (uint32_t)(uintptr_t)&g_uart_debug_scratch) return (void *)&g_uart_debug_scratch;
    if(address >= 0x08000000 && address < 0x08080000) return ram.bytes+address-0x08000000;
    if(address >= 0x20000000 && address < 0x20010000) return ram.bytes+address-0x20000000;
    if(address >= 0x20100000 && address < 0x20140000) return ram.bytes+address-0x20100000;
    abort();
}
bool dbg_uart_try_send(const uint8_t *data,uint16_t size) {memcpy(response,data,size);response_len=size;return true;}
bool dbg_uart_try_send_low(const uint8_t *data,uint16_t size) {return dbg_uart_try_send(data,size);}
uint32_t dbg_get_timestamp_us(void) {return 0;}
uint8_t dbg_control_start(void) {abort();}
uint8_t dbg_control_stop(void) {abort();}
uint8_t dbg_control_set_run_mode(uint8_t mode) {(void)mode;abort();}
uint8_t dbg_control_clear_fault_lock(void) {abort();}
#define ZERO32(name) uint32_t name(void) {return 0;}
#define ZERO16(name) uint16_t name(void) {return 0;}
ZERO32(dbg_uart_get_tx_recovery_count) ZERO32(dbg_get_last_init_error)
ZERO32(dbg_get_stim1_max_cycles) ZERO32(dbg_get_stim3_max_cycles)
ZERO32(dbg_uart_get_high_overflow) ZERO32(dbg_uart_get_low_overflow)
ZERO16(dbg_uart_get_high_water) ZERO16(dbg_uart_get_low_water)
int main(int argc,char **argv) {
    uint8_t frame[256];
    debug_monitor_init();
    review_idle();
    for(unsigned i=0;i<sizeof(ram.bytes);i++)ram.bytes[i]=(uint8_t)(i^0x5a);
    for(int a=1;a<argc;a++) {
        size_t n=strlen(argv[a])/2;
        if(n>sizeof(frame))return 2;
        for(size_t i=0;i<n;i++) {unsigned v;if(sscanf(argv[a]+i*2,"%2x",&v)!=1)return 3;frame[i]=(uint8_t)v;}
        response_len=0;
        debug_monitor_receive_frame(frame,(uint16_t)n);
        for(unsigned i=0;i<response_len;i++)printf("%02x",response[i]);
        puts("");
    }
    return 0;
}
