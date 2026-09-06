/* Independent review HAL/state fixtures. No implementation test helper included. */
#include <assert.h>
static uint32_t review_mask;
static unsigned review_disables, review_restores, review_inject_fault;
static uint16_t review_latched, review_event;
static uint32_t __get_PRIMASK(void) { return review_mask; }
static void __disable_irq(void) {
    review_mask = 1;
    ++review_disables;
    if (review_inject_fault) review_latched = 1;
}
static void __set_PRIMASK(uint32_t mask) { review_mask = mask; ++review_restores; }
#include "debug_parameter_write_impl.h"
BspFsmObj g_bspFsmObj;
FsmObj g_fsmObj;
InvCurrLoopObj g_invCurrLoopObj;
InvVoltLoopObj g_invVoltLoopObj;
UrmsLoopObj g_uRmsLoopObj;
InvMuxObj g_invMuxObj;
HalPwmSemObj g_pwmSemObj;
uint16 PROTECT_IsLatched(void) { assert(review_mask == 1); return review_latched; }
uint16 HAL_PROTECT_GetLastEvent(void) { assert(review_mask == 1); return review_event; }
static void review_idle(void) {
    g_fsmObj.currentState = FSM_STATE_IDLE;
    g_pwmSemObj.isDrvEnable = HAL_PWM_DRV_DISABLE;
    Dm_RefreshParameterObservation();
}
