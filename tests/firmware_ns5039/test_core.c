/* Executes the production parser and codec, with only UART, DWT and physical
 * address seams. Control algorithms are neither linked nor simulated. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "debug_monitor_core.c"
InvCurrLoopCfg g_invCurrLoopCfg;
InvVoltLoopCfg g_invVoltLoopCfg;
UrmsLoopCfg g_uRmsLoopCfg;
struct TestDwt test_dwt;
static union { uint64_t align; uint8_t data[0x80000]; } memory;
static uint8_t tx[256];
static uint16_t tx_len;
static unsigned tx_count, reads, checks;
static bool busy;
#define CHECK(x) do { checks++; if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); exit(1); } } while(0)
void *ns5039_test_pointer(uint32_t a) {
    reads++;
    if (a == (uint32_t)(uintptr_t)&g_uart_debug_scratch) return (void *)&g_uart_debug_scratch;
    for(unsigned i=0;i<sizeof(s_writeRules)/sizeof(s_writeRules[0]);i++) if(a==(uint32_t)s_writeRules[i].address) return (void *)s_writeRules[i].address;
    if (a >= DM_FLASH_START && a < DM_FLASH_END) return memory.data + a-DM_FLASH_START;
    if (a >= DM_DTCM_START && a < DM_DTCM_END) return memory.data + a-DM_DTCM_START;
    if (a >= DM_SRAM_START && a < DM_SRAM_END) return memory.data + a-DM_SRAM_START;
    fprintf(stderr,"unexpected MCU address %08x\n", a); abort();
}
bool dbg_uart_try_send(const uint8_t *d,uint16_t n) { if(busy) return false; memcpy(tx,d,n);tx_len=n;tx_count++;return true; }
bool dbg_uart_try_send_low(const uint8_t *d,uint16_t n) { return dbg_uart_try_send(d,n); }
uint32_t dbg_get_timestamp_us(void) { return 0; }
uint8_t dbg_control_start(void) { abort(); }
uint8_t dbg_control_stop(void) { abort(); }
uint8_t dbg_control_set_run_mode(uint8_t m) { (void)m;abort(); }
uint8_t dbg_control_clear_fault_lock(void) { abort(); }
#define ZERO32(n) uint32_t n(void) {return 0;}
#define ZERO16(n) uint16_t n(void) {return 0;}
ZERO32(dbg_uart_get_tx_recovery_count) ZERO32(dbg_get_last_init_error)
ZERO32(dbg_get_stim1_max_cycles) ZERO32(dbg_get_stim3_max_cycles)
ZERO32(dbg_uart_get_high_overflow) ZERO32(dbg_uart_get_low_overflow)
ZERO16(dbg_uart_get_high_water) ZERO16(dbg_uart_get_low_water)
/* Independent CRC oracle: bit-by-bit long division, not the production helper. */
static uint16_t crc(const uint8_t *p,size_t n) {
    unsigned c=65535; while(n--) { c ^= *p++; for(int k=0;k<8;k++) c=(c&1)?(c/2)^40961:c/2; } return (uint16_t)c;
}
static size_t frame(uint8_t *f,uint8_t cmd,uint16_t seq,uint32_t addr,const uint8_t *p,size_t n) {
    memset(f,0,256); f[0]=0xa5;f[1]=0x5a;f[2]=1;f[3]=cmd;
    f[4]=(uint8_t)seq;f[5]=(uint8_t)(seq>>8);
    for(int i=0;i<4;i++) f[6+i]=(uint8_t)(addr>>(8*i));
    f[10]=(uint8_t)n;f[11]=(uint8_t)(n>>8); if(n)memcpy(f+12,p,n);
    uint16_t c=crc(f,12+n); f[12+n]=(uint8_t)c;f[13+n]=(uint8_t)(c>>8); return n+14;
}
static void send(uint8_t cmd,uint32_t a,const uint8_t *p,size_t n) {uint8_t f[256];size_t l=frame(f,cmd,0x1234,a,p,n);tx_len=0; debug_monitor_receive_frame(f,(uint16_t)l);}
static void status(uint8_t s) { CHECK(tx_len>=11);CHECK(tx[6]==s);CHECK(tx[3]==(s?255:tx[3]));CHECK(tx[4]==0x34&&tx[5]==0x12);CHECK(crc(tx,tx_len-2)==(uint16_t)(tx[tx_len-2]+256*tx[tx_len-1])); }
static void sample(uint8_t *p,unsigned count,unsigned size) {
    memset(p,0,128);p[1]=0xa0;p[2]=0x86;p[3]=1; /* 100000 us extended period */ p[5]=(uint8_t)count;
    for(unsigned i=0;i<count;i++){unsigned a=0x20000000+8*i;for(int j=0;j<4;j++)p[6+6*i+j]=(uint8_t)(a>>(8*j));p[10+6*i]=(uint8_t)size;}
}
int main(int argc,char **argv) {
    uint8_t p[192],f[256];size_t n;
    debug_monitor_init();for(unsigned i=0;i<sizeof(memory.data);i++)memory.data[i]=(uint8_t)i;
    CHECK(crc((const uint8_t *)"123456789",9)==0x4b37);
    p[0]=181;send(1,0x20000000,p,1);status(0);CHECK(tx_len==192);CHECK(!memcmp(tx+9,memory.data,181));
    for(unsigned i=182;i<=193;i++){unsigned before=reads;p[0]=(uint8_t)i;send(1,0x20000000,p,1);status(4);CHECK(reads==before);}
    p[0]=0;send(1,0x20000000,p,1);status(4);
    p[0]=2;send(1,0x0807ffff,p,1);status(3);send(1,0x2000ffff,p,1);status(3);send(1,0x2013ffff,p,1);status(3);send(1,0xffffffff,p,1);status(3);
    p[0]=1;n=frame(f,1,0x1234,0x20000000,p,1);tx_len=0;debug_monitor_receive_frame(f,13);CHECK(tx_len==0);debug_monitor_receive_frame(f,(uint16_t)(n-1));status(4);
    f[n-1]^=1;debug_monitor_receive_frame(f,(uint16_t)n);status(1);
    p[0]=16;for(unsigned i=0;i<16;i++){unsigned a=0x20000000+i*8;for(int j=0;j<4;j++)p[1+i*5+j]=(uint8_t)(a>>(8*j));p[5+i*5]=8;}
    send(3,0,p,81);status(0);CHECK(tx_len==139);CHECK(!memcmp(tx+9,memory.data,128));p[0]=17;send(3,0,p,86);status(4);
    sample(p,16,4);send(4,0,p,102);status(0);CHECK(s_list[0].sampleBytes==64);CHECK(tx_len==15);CHECK(Dm_GetU32(tx+9)==100000);
    DmSampleList saved=s_list[0];sample(p,17,4);send(4,0,p,108);status(7);CHECK(!memcmp(&saved,&s_list[0],sizeof(saved)));
    sample(p,9,8);send(4,0,p,60);status(3);CHECK(!memcmp(&saved,&s_list[0],sizeof(saved)));
    sample(p,8,8);send(4,0,p,54);status(0);CHECK(s_list[0].sampleBytes==64);
    /* 4-byte alignment for double; reject only 2-byte alignment. */
    p[6]=4;send(4,0,p,54);status(0);p[6]=2;send(4,0,p,54);status(3);
    p[0]=1;send(2,0x20000000,p,1);status(6);send(10,0,NULL,0);status(6);
    /* Actual ACL rejects non-finite/out-of-range values before memory access. */
    float value=110.0f;memcpy(p,&value,4);send(8,(uint32_t)(uintptr_t)&g_uRmsLoopCfg.urmsRef,p,4);status(0);CHECK(g_uRmsLoopCfg.urmsRef==110.0f);
    p[0]=0;p[1]=0;p[2]=0x80;p[3]=0x7f;send(8,(uint32_t)(uintptr_t)&g_uRmsLoopCfg.urmsRef,p,4);status(6);CHECK(g_uRmsLoopCfg.urmsRef==110.0f);
    value=141.0f;memcpy(p,&value,4);send(8,(uint32_t)(uintptr_t)&g_uRmsLoopCfg.urmsRef,p,4);status(6);
    p[0]=0x55;send(2,(uint32_t)(uintptr_t)&g_uart_debug_scratch,p,1);status(0);CHECK(g_uart_debug_scratch==0x55);
    send(2,(uint32_t)(uintptr_t)&g_uart_debug_scratch+3,p,2);status(6);CHECK(g_uart_debug_scratch==0x55);
    debug_monitor_init();busy=true;send(7,0,NULL,0);CHECK(tx_len==0&&s_response.pending==1);send(7,0,NULL,0);CHECK(g_dm_response_drops==1);debug_monitor_task_1ms();CHECK(s_txBusyRetries==1);busy=false;unsigned before=tx_count;debug_monitor_task_1ms();CHECK(tx_count==before+1&&s_response.pending==0);CHECK(tx_len==185);
    debug_monitor_init();sample(p,1,4);send(4,0,p,12);status(0);p[0]=0;send(5,0,p,1);status(0);busy=true;for(unsigned i=0;i<140000;i++)debug_monitor_capture_isr();CHECK(s_ringDrops>0);busy=false;debug_monitor_task_1ms();
    debug_monitor_init();send(7,0,NULL,0);status(0);CHECK(tx_len==185&&tx[7]==174);CHECK(!memcmp(tx+9+94,"PSC1\1\120",6));CHECK(!memcmp(tx+9+100,g_powerscope_build_id,32));CHECK(tx[9+132]==0xfe&&tx[9+133]==0x71&&tx[9+136]==0x6f);
    if(argc>1){FILE *out=fopen(argv[1],"w");CHECK(out!=NULL);for(unsigned i=0;i<tx_len;i++)fprintf(out,"%02x",tx[i]);fclose(out);}
    printf("NS5039 production C: %u checks passed\n",checks);return 0;
}
