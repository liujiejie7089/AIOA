package cn.aioa.common.http;

import java.net.http.HttpClient;

/**
 * 后端访问 Python agent（FastAPI / uvicorn）时的 HttpClient 工厂 —— 唯一入口。
 *
 * <h3>为什么必须显式 HTTP/1.1（不要删掉这一行）</h3>
 * {@code java.net.http.HttpClient} 默认 HTTP/2 优先。对**明文** {@code http://} 目标，
 * 它会先发一个 h2c 升级请求：
 * <pre>
 * POST /internal/v1/complete HTTP/1.1
 * Connection: Upgrade, HTTP2-Settings
 * Upgrade: h2c
 * HTTP2-Settings: AAEAAEAAAAIAAAA...
 * Content-Length: 44          &lt;- 声明了长度
 * （空行，随后并无 body）
 * </pre>
 * 请求体被**推迟到升级成功之后**才发送。而 uvicorn 不支持 h2c 升级：未装 httptools
 * 时它走 h11 实现，会打出 {@code Unsupported upgrade request.} 后直接把一个**空 body**
 * 的请求派发给 FastAPI，于是 FastAPI 返回
 * {@code 422 {"loc":["body"],"msg":"Field required","input":null}}；
 * 迟到的 body 字节还会让 uvicorn 再打一条 {@code Invalid HTTP request received.}。
 *
 * <p>实测（2026-09-22）：同一条 POST 打 agent，默认 HTTP/2 优先 → 422；显式 HTTP/1.1 → 200。
 * 走 Spring {@code WebClient}（Reactor Netty，明文默认 HTTP/1.1）的
 * {@code /internal/v1/runs}、{@code /internal/v1/tasks} 一直正常，正是反证。</p>
 *
 * <p>不要依赖 agent 侧装没装 httptools 来兜底：agent 与本体是两个独立镜像/进程，
 * 其可选依赖不该决定后端请求体能否送达。静态守卫
 * {@code scripts/_check_agent_httpclient.py} 会拦截本类的替代写法。</p>
 */
public final class AgentHttpClient {

    private AgentHttpClient() {
    }

    /**
     * 建一个「只用于访问 agent」的客户端构造器，已固定 HTTP/1.1。
     * 调用方可继续链式设置 connectTimeout / followRedirects 等。
     */
    public static HttpClient.Builder agentBuilder() {
        return HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1);
    }
}
