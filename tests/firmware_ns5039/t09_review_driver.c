#define main baseline_review_main
#include "review_driver.c"
#undef main

/* Assemble a request independently, not with firmware serialization helpers. */
static void review_send(uint8_t command, uint32_t address, uint32_t bits) {
    uint8_t frame[18] = {0xa5,0x5a,1,command,0x45,0x23,0,0,0,0,4,0};
    for (unsigned j=0;j<4;++j) { frame[6+j]=(uint8_t)(address>>(8*j)); frame[12+j]=(uint8_t)(bits>>(8*j)); }
    uint16_t crc=0xffff;
    for (unsigned j=0;j<16;++j) {
        crc ^= frame[j];
        for (unsigned k=0;k<8;++k) crc=(uint16_t)((crc>>1)^((crc&1)?0xa001:0));
    }
    frame[16]=(uint8_t)crc; frame[17]=(uint8_t)(crc>>8);
    response_len=0;
    debug_monitor_receive_frame(frame,sizeof(frame));
}
int main(int argc,char **argv) {
    if (argc != 4) return 2;
    debug_monitor_init(); review_idle();
    g_invVoltLoopCfg.voltCfg.kp=0.25f;
    const char *scenario=argv[1];
    if (!strcmp(scenario,"run")) g_fsmObj.currentState=FSM_STATE_RUN;
    else if (!strcmp(scenario,"stopping")) {g_fsmObj.currentState=FSM_STATE_SHUTDOWN;g_bspFsmObj.turnOnOff=TURN_OFF;}
    else if (!strcmp(scenario,"unknown")) g_fsmObj.currentState=65535;
    else if (!strcmp(scenario,"requested_on")) g_bspFsmObj.turnOnOff=TURN_ON;
    else if (!strcmp(scenario,"pending_pwm")) g_pwmSemObj.drvEnablePend=1;
    else if (!strcmp(scenario,"bad_pwm")) g_pwmSemObj.isDrvEnable=0;
    else if (!strcmp(scenario,"unknown_consumer")) g_invCurrLoopObj.state=65535;
    else if (!strcmp(scenario,"fault")) g_bspFsmObj.faultLatched=1;
    else if (!strcmp(scenario,"protect_unknown")) review_event=65535;
    else if (!strcmp(scenario,"race")) review_inject_fault=1;
    else if (!strcmp(scenario,"masked")) review_mask=1;
    else if (!strcmp(scenario,"wrap")) g_dm_control_observation.generation=0xfffffffe;
    else if (strcmp(scenario,"idle") && strcmp(scenario,"scratch_fault")) return 3;
    uint32_t address=(uint32_t)(uintptr_t)&g_invVoltLoopCfg.voltCfg.kp;
    if (!strcmp(scenario,"scratch_fault")) {address=(uint32_t)(uintptr_t)&g_uart_debug_scratch; review_latched=1;}
    review_send((uint8_t)strtoul(argv[2],NULL,0),address,(uint32_t)strtoul(argv[3],NULL,16));
    uint32_t bits; memcpy(&bits,&g_invVoltLoopCfg.voltCfg.kp,4);
    printf("%u %08x %u %u %u %u %u\n",response_len?response[6]:255,bits,
      review_mask,review_disables,review_restores,g_dm_control_observation.generation,g_dm_last_write_status);
    return 0;
}
