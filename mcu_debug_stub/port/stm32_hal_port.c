/**
 * stm32_hal_port.c — STM32 HAL 移植示例
 *
 * 展示如何将 debug_monitor 移植到 STM32 (HAL 库)。
 * 用户只需实现 3 个 HAL 接口函数 + 在 main.c 中调用 init。
 */
#include "../debug_monitor.h"
#include "stm32g4xx_hal.h"
#include <string.h>

/* ====== 用户全局变量 (会被 PowerScope 监控) ====== */
// 这些变量的地址会出现在 .elf 符号表中
volatile float g_pv_voltage = 0.0f;     // PV电压
volatile float g_pv_current = 0.0f;     // PV电流
volatile float g_grid_voltage = 0.0f;   // 电网电压
volatile float g_grid_freq = 0.0f;      // 电网频率
volatile float g_output_power = 0.0f;   // 输出功率
volatile float g_id = 0.0f;            // d轴电流
volatile float g_iq = 0.0f;            // q轴电流
volatile uint16_t g_duty = 0;          // 占空比
volatile float g_pi_kp = 0.5f;        // PI Kp
volatile float g_pi_ki = 80.0f;       // PI Ki
volatile uint8_t g_run_state = 0;     // 运行状态
volatile uint8_t g_fault_code = 0;    // 故障码

/* ====== UART 句柄 (在 main.c 中初始化) ====== */
extern UART_HandleTypeDef huart2;
static uint8_t s_rx_byte;

/* ====== DMA 发送缓冲 ====== */
#define TX_DMA_BUF_SIZE 1024
static uint8_t s_tx_dma_buf[TX_DMA_BUF_SIZE];
static volatile bool s_tx_busy = false;

/* ====== HAL 接口实现 ====== */

void dbg_uart_send(const uint8_t* data, uint16_t len) {
    if (s_tx_busy) {
        /* 发送忙: 丢弃 (生产环境可用队列缓冲) */
        return;
    }
    if (len > TX_DMA_BUF_SIZE) len = TX_DMA_BUF_SIZE;
    memcpy(s_tx_dma_buf, data, len);
    s_tx_busy = true;
    HAL_UART_Transmit_DMA(&huart2, s_tx_dma_buf, len);
}

uint32_t dbg_get_timestamp_us(void) {
    /* TIM2 配置为 1us 分辨率 (170MHz / 170 = 1MHz) */
    return __HAL_TIM_GET_COUNTER(&htim2);
}

void dbg_system_reset(void) {
    NVIC_SystemReset();
}

/* ====== UART 接收回调 (每个字节) ====== */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart) {
    if (huart == &huart2) {
        debug_monitor_feed_byte(s_rx_byte);
        HAL_UART_Receive_IT(&huart2, &s_rx_byte, 1);
    }
}

/* ====== DMA 发送完成回调 ====== */
void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart) {
    if (huart == &huart2) {
        s_tx_busy = false;
    }
}

/* ====== SysTick 回调 (1ms) ====== */
void HAL_SYSTICK_Callback(void) {
    debug_monitor_on_tick();
}

/* ====== 初始化函数 (在 main() 中调用) ====== */
void power_scope_init(void) {
    debug_monitor_init();

    /* 配置设备信息 */
    dm_device_info_t info = {
        .mcu_model = "STM32G474",
        .cpu_freq_hz = 170000000,
        .elf_crc = 0,  /* post-build 脚本填充 */
        .protocol_ver = 0x0001,
        .fw_version = "1.0.0",
    };
    debug_monitor_set_info(&info);

    /* 启动 UART 接收 */
    HAL_UART_Receive_IT(&huart2, &s_rx_byte, 1);
}

/*
 * ====== main.c 集成示例 ======
 *
 * int main(void) {
 *     HAL_Init();
 *     SystemClock_Config();
 *     MX_GPIO_Init();
 *     MX_USART2_UART_Init();
 *     MX_TIM2_Init();
 *     HAL_TIM_Base_Start(&htim2);
 *
 *     power_scope_init();  // 初始化调试桩
 *
 *     while (1) {
 *         // 用户功率控制主循环
 *         power_control_loop();
 *     }
 * }
 *
 * ====== 中断优先级配置 (在 NVIC 中) ======
 *   PWM/ADC 中断:  优先级 0 (最高, 不可被调试桩抢占)
 *   故障保护:      优先级 1
 *   SysTick:       优先级 2 (采样列表执行)
 *   USART2 (调试): 优先级 3 (最低, 可被任意抢占)
 *
 * ====== UART 配置建议 ======
 *   波特率: 921600 (推荐) 或 115200
 *   数据位: 8, 校验: None, 停止位: 1
 *   推荐: 启用 DMA 发送 + 中断接收
 */
