package cn.aioa.tool.sdk;

/**
 * 工具声明的落地端（SPI）。
 *
 * <p>{@link AioaToolScanner} 只负责「发现」注解，发现之后交给谁由本接口决定：
 * 平台内由 {@code aioa-bridge} 实现（把声明写进 {@code tool_definition} 并加入本地注册表），
 * 独立子应用可以换成「上报到远端注册中心」。方向是「SDK 定义接口、平台实现」，
 * 因此 SDK 不需要知道桥接层、桥接层可以自由变更自己的存储。</p>
 *
 * <p><b>没有实现时的行为</b>：扫描器静默跳过（仅记一条 info 日志）。
 * 这样把 SDK 单独引入到一个尚未接平台的项目里不会导致启动失败 ——
 * 注解先写、平台后接，是正常的落地顺序。</p>
 */
public interface ToolDefinitionSink {

    /** 注册一个工具声明（重复注册同一 code 时应按「覆盖」语义处理，便于本地改代码即生效）。 */
    void register(ToolSpec spec);
}
