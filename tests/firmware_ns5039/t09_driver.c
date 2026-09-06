/* Reuse transport/CRC helpers, while exercising the production state policy. */
#define main t03_original_main
#include "test_core.c"
#undef main
static void write_ref(uint8_t expected) {
    float value=111.0f;
    g_uRmsLoopCfg.urmsRef=110.0f;
    send(DM_CMD_SET_PARAM,(uint32_t)(uintptr_t)&g_uRmsLoopCfg.urmsRef,(uint8_t *)&value,4);
    status(expected);
    CHECK(g_dm_last_write_status==expected);
    CHECK(g_uRmsLoopCfg.urmsRef==(expected==0?111.0f:110.0f));
    CHECK(test_primask==0);
    CHECK(!(g_dm_control_observation.generation&1));
    CHECK(g_dm_control_observation.parameter_write_status==expected);
}
int main(void) {
    debug_monitor_init(); t09_reset_state();
    for(unsigned i=0;i<sizeof(s_writeRules)/sizeof(s_writeRules[0]);i++) {
        float value=(s_writeRules[i].minValue+s_writeRules[i].maxValue)/2;
        for(unsigned cmd=2;cmd<=8;cmd+=6) {
            *(float *)s_writeRules[i].address=-999;
            send((uint8_t)cmd,(uint32_t)s_writeRules[i].address,(uint8_t *)&value,4);
            status(0); CHECK(*(float *)s_writeRules[i].address==value);
        }
    }
    for(unsigned state=0;state<8;state++) {
        t09_reset_state();g_fsmObj.currentState=(uint16_t)state;
        write_ref(state==FSM_STATE_IDLE?0:DM_STATUS_ERR_BUSY);
        CHECK(g_dm_control_observation.fsm_state==state);
    }
    t09_reset_state();g_bspFsmObj.turnOnOff=TURN_ON;write_ref(5);
    /* STOP accepted while still RUN does not authorize a write. */
    g_bspFsmObj.turnOnOff=TURN_OFF;g_fsmObj.currentState=FSM_STATE_RUN;write_ref(5);
    t09_reset_state();g_bspFsmObj.faultLatched=1;write_ref(6);
    t09_reset_state();g_bspFsmObj.shutdownRequest=1;write_ref(6);
    t09_reset_state();g_bspFsmObj.hwProtectWait=1;write_ref(6);
    t09_reset_state();test_protect_latched=1;write_ref(6);
    for(unsigned event=0;event<10;event++) {
        t09_reset_state();test_protect_event=(uint16_t)event;
        write_ref(event<=1?0:6);
    }
    t09_reset_state();g_invCurrLoopObj.state=1;write_ref(5);
    t09_reset_state();g_invVoltLoopObj.state=1;write_ref(5);
    t09_reset_state();g_uRmsLoopObj.state=1;write_ref(5);
    t09_reset_state();g_invMuxObj.state=1;write_ref(5);
    t09_reset_state();g_pwmSemObj.isDrvEnable=HAL_PWM_DRV_ENABLE;write_ref(5);
    t09_reset_state();g_pwmSemObj.isDrvEnable=0;write_ref(5);
    t09_reset_state();g_pwmSemObj.drvEnablePend=1;write_ref(5);
    /* Scratch bypasses only the runtime gate, never the scratch boundary. */
    uint8_t byte=0x67; test_protect_latched=1;
    unsigned disabled=test_disable_count;
    send(2,(uint32_t)(uintptr_t)&g_uart_debug_scratch,&byte,1);status(0);
    CHECK(g_uart_debug_scratch==byte); CHECK(test_disable_count==disabled);
    t09_reset_state();float v=0.5f;
    send(8,(uint32_t)(uintptr_t)&g_invCurrLoopCfg.freqCfg.kp,(uint8_t *)&v,4);status(6);
    uint32_t bad[]={0x7fc00000,0x7f800000,0xff800000};
    for(unsigned i=0;i<3;i++) {
        disabled=test_disable_count;
        send(8,(uint32_t)(uintptr_t)&g_invVoltLoopCfg.voltCfg.kp,(uint8_t *)&bad[i],4);status(6);
        CHECK(test_disable_count==disabled);
    }
    /* Caller already masked interrupts: restoring must not enable them. */
    test_primask=1;
    send(8,(uint32_t)(uintptr_t)&g_invVoltLoopCfg.voltCfg.kp,(uint8_t *)&v,4);status(0);
    CHECK(test_primask==1);CHECK(test_disable_count==test_restore_count);
    test_primask=0;
    /* Watchdog stops data streaming, with no change in motor/control state. */
    g_fsmObj.currentState=FSM_STATE_RUN;s_hostWatchdogArmed=1;s_lastHostUs=0u-DM_HOST_TIMEOUT_US-1u;
    debug_monitor_task_1ms();CHECK(s_hostWatchdogArmed==0);write_ref(5);
    puts("T09 production runtime policy passed");
    printf("T09 checks: %u\n",checks);return 0;
}
