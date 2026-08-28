/**
 * power_core.c — 库入口，版本信息
 */
#include "power_core.h"

static const char s_version[] = "PowerScope Core v0.1.0";

__declspec(dllexport) const char* pc_get_version(void) {
    return s_version;
}
