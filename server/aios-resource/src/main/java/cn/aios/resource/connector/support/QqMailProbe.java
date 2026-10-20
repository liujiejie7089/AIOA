package cn.aios.resource.connector.support;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.regex.Pattern;

/**
 * QQ 邮箱 IMAP 凭据真实校验探针（无第三方依赖，纯 JDK TLS + 文本协议）。
 *
 * <p><b>流程</b>：TLS 连 {@code imap.qq.com:993} → 读问候行（须 {@code * OK}）→
 * 发 {@code a1 LOGIN "<email>" "<authCode>"}（引号/反斜杠转义）→ 读 {@code a1 OK}（成功）/
 * {@code a1 NO|a1 BAD}（失败，带出服务端原文）→ 尽力 {@code a2 LOGOUT} → 关 socket。</p>
 *
 * <p><b>安全纪律</b>：<b>绝不</b>把授权码写进任何日志；失败时只把服务端公开的中文原因（截断到 200 字符）
 * 返回给调用方用于前端提示。连接 / 读超时分别 6s / 8s，避免网络不可达时挂死线程。</p>
 */
@Slf4j
@Component
public class QqMailProbe {

    private static final String HOST = "imap.qq.com";
    private static final int PORT = 993;
    private static final int CONNECT_TIMEOUT_MS = 6000;
    private static final int READ_TIMEOUT_MS = 8000;
    private static final int MAX_REASON = 200;

    private static final String OK = "a1 OK";
    private static final String NO = "a1 NO";
    private static final String BAD = "a1 BAD";

    /** 简单邮箱格式校验（仅用于参数守卫，真正的成败由 IMAP 登录决定）。 */
    private static final Pattern EMAIL = Pattern.compile(
            "^[A-Za-z0-9+._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$");

    /**
     * 校验 QQ 邮箱授权码。
     *
     * @return 非 null = 失败原因（已截断到 200 字符，不含授权码）；null = 校验成功。
     */
    public String verify(String email, String authCode) {
        if (email == null || authCode == null || !EMAIL.matcher(email).matches()) {
            return "邮箱格式不正确";
        }
        SSLSocket socket = null;
        try {
            SSLSocketFactory factory = (SSLSocketFactory) SSLSocketFactory.getDefault();
            socket = (SSLSocket) factory.createSocket();
            socket.connect(new InetSocketAddress(HOST, PORT), CONNECT_TIMEOUT_MS);
            socket.setSoTimeout(READ_TIMEOUT_MS);

            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
            OutputStream out = socket.getOutputStream();

            // 1) 问候行
            String greeting = reader.readLine();
            if (greeting == null || !greeting.startsWith("* OK")) {
                return "IMAP 服务握手失败";
            }

            // 2) LOGIN（对引号与反斜杠转义）
            String cmd = "a1 LOGIN " + quote(email) + " " + quote(authCode) + "\r\n";
            out.write(cmd.getBytes(StandardCharsets.UTF_8));
            out.flush();

            // 3) 读取 a1 响应
            String resp = null;
            while (true) {
                String line = reader.readLine();
                if (line == null) {
                    break;
                }
                if (line.startsWith("a1 ")) {
                    resp = line;
                    break;
                }
            }
            if (resp == null) {
                return "未收到邮箱服务响应";
            }
            if (resp.startsWith(OK)) {
                return null; // 成功
            }
            if (resp.startsWith(NO) || resp.startsWith(BAD)) {
                return truncate(resp.substring(4).trim());
            }
            return truncate("未知响应：" + resp);
        } catch (java.net.SocketTimeoutException e) {
            return "连接邮箱服务超时";
        } catch (Exception e) {
            // 仅记录异常类型，绝不记录邮箱 / 授权码
            log.debug("QQ 邮箱 IMAP 校验异常: {}", e.getClass().getSimpleName());
            return "无法连接邮箱服务（" + e.getClass().getSimpleName() + "）";
        } finally {
            if (socket != null) {
                try {
                    // 尽力登出，忽略失败
                    try {
                        OutputStream o = socket.getOutputStream();
                        o.write("a2 LOGOUT\r\n".getBytes(StandardCharsets.UTF_8));
                        o.flush();
                    } catch (Exception ignored) {
                    }
                } finally {
                    try {
                        socket.close();
                    } catch (Exception ignored) {
                    }
                }
            }
        }
    }

    private static String quote(String s) {
        String escaped = s.replace("\\", "\\\\").replace("\"", "\\\"");
        return "\"" + escaped + "\"";
    }

    private static String truncate(String s) {
        if (s == null) {
            return "";
        }
        return s.length() <= MAX_REASON ? s : s.substring(0, MAX_REASON);
    }
}
