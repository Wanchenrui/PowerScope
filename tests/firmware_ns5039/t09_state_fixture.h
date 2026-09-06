/* Only hardware interrupt/protection observations are replaced. */
static uint32_t test_primask, test_disable_count, test_restore_count;
static uint16_t test_protect_latched, test_protect_event;
static uint32_t __get_PRIMASK(void) { return test_primask; }
static void __disable_irq(void) { test_primask = 1; test_disable_count++; }
static void __set_PRIMASK(uint32_t value) { test_primask = value; test_restore_count++; }
#include "debug_parameter_write_impl.h"
BspFsmObj g_bspFsmObj;
FsmObj g_fsmObj;
InvCurrLoopObj g_invCurrLoopObj;
InvVoltLoopObj g_invVoltLoopObj;
UrmsLoopObj g_uRmsLoopObj;
InvMuxObj g_invMuxObj;
HalPwmSemObj g_pwmSemObj;
uint16 PROTECT_IsLatched(void) { assert(test_primask == 1); return test_protect_latched; }
uint16 HAL_PROTECT_GetLastEvent(void) { assert(test_primask == 1); return test_protect_event; }
static void t09_reset_state(void) {
    memset(&g_bspFsmObj,0,sizeof(g_bspFsmObj));
    memset(&g_invCurrLoopObj,0,sizeof(g_invCurrLoopObj));
    memset(&g_invVoltLoopObj,0,sizeof(g_invVoltLoopObj));
    memset(&g_uRmsLoopObj,0,sizeof(g_uRmsLoopObj));
    memset(&g_invMuxObj,0,sizeof(g_invMuxObj));
    memset(&g_pwmSemObj,0,sizeof(g_pwmSemObj));
    g_fsmObj.currentState = FSM_STATE_IDLE;
    g_pwmSemObj.isDrvEnable = HAL_PWM_DRV_DISABLE;
    test_protect_latched = 0; test_protect_event = HAL_PROTECT_EVENT_NONE;
    test_primask = 0;
    Dm_RefreshParameterObservation();
}
