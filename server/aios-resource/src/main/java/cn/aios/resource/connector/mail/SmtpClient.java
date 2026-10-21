package cn.aios.resource.connector.mail;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.Base64;
import java.util.regex.Pattern;

/**
 * 纯 JDK SMTPS 客户端（smtp.qq.com:465 SSL，连接 6s / 读 15s）。不引入任何第三方库。
 *
 * <p>流程：EHLO → AUTH LOGIN（base64 用户名 / 授权码）→ MAIL FROM → 多个 RCPT TO（to + cc）
 * → DATA（UTF-8 正文 base64 按 76 列折行，行首 {@code .} 转义为 {@code ..}）→ {@code .} → QUIT。</p>
 *
 * <p><b>头注入防护</b>：{@code to/cc/subject} 含 {@code \r}/{\@code \n} 一律拒绝——这些参数来自模型，
 * 绝不能原样拼进 SMTP 头。授权码与完整正文绝不进入日志或异常。</p>
 */
@Slf4j
@Component
public class SmtpClient {

    private static final String HOST = "smtp.qq.com";
    private static final int PORT = 465;
    private static final int CONNECT_TIMEOUT_MS = 6000;
    private static final int READ_TIMEOUT_MS = 15000;
    private static final Pattern CRLF = Pattern.compile("[\\r\\n]");

    public String send(String email, String authCode, String to, String cc, String subject, String body) {
        if (hasCrlf(to) || hasCrlf(cc) || hasCrlf(subject)) {
            throw new MailException("收件人 / 抄送 / 主题含非法换行字符（疑似头注入）");
        }
        Conn c = new Conn();
        boolean opened = false;
        try {
            SSLSocketFactory f = (SSLSocketFactory) SSLSocketFactory.getDefault();
            c.socket = (SSLSocket) f.createSocket();
            c.socket.connect(new InetSocketAddress(HOST, PORT), CONNECT_TIMEOUT_MS);
            c.socket.setSoTimeout(READ_TIMEOUT_MS);
            c.in = c.socket.getInputStream();
            c.out = c.socket.getOutputStream();
            opened = true;
            expect(c, 220);
            String domain = email.contains("@") ? email.substring(email.indexOf('@') + 1) : "localhost";
            sendLine(c, "EHLO " + domain);
            expect(c, 250);
            sendLine(c, "AUTH LOGIN");
            expect(c, 334);
            sendLine(c, Base64.getEncoder().encodeToString(email.getBytes(StandardCharsets.UTF_8)));
            expect(c, 334);
            sendLine(c, Base64.getEncoder().encodeToString(authCode.getBytes(StandardCharsets.UTF_8)));
            expect(c, 235);
            sendLine(c, "MAIL FROM:<" + email + ">");
            expect(c, 250);
            for (String addr : splitAddrs(to)) {
                sendLine(c, "RCPT TO:<" + addr + ">");
                expect(c, 250);
            }
            if (cc != null && !cc.isBlank()) {
                for (String addr : splitAddrs(cc)) {
                    sendLine(c, "RCPT TO:<" + addr + ">");
                    expect(c, 250);
                }
            }
            sendLine(c, "DATA");
            expect(c, 354);
            String messageId = "<" + UUID.randomUUID() + "@" + domain + ">";
            StringBuilder msg = new StringBuilder();
            msg.append("From: ").append(email).append("\r\n");
            msg.append("To: ").append(to).append("\r\n");
            if (cc != null && !cc.isBlank()) msg.append("Cc: ").append(cc).append("\r\n");
            msg.append("Subject: =?UTF-8?B?")
                    .append(Base64.getEncoder().encodeToString(subject.getBytes(StandardCharsets.UTF_8)))
                    .append("?=\r\n");
            msg.append("Date: ").append(rfcDate()).append("\r\n");
            msg.append("Message-ID: ").append(messageId).append("\r\n");
            msg.append("MIME-Version: 1.0\r\n");
            msg.append("Content-Type: text/plain; charset=UTF-8\r\n");
            msg.append("Content-Transfer-Encoding: base64\r\n");
            msg.append("\r\n");
            String b64 = Base64.getEncoder().encodeToString(body.getBytes(StandardCharsets.UTF_8));
            for (int i = 0; i < b64.length(); i += 76) {
                msg.append(b64, i, Math.min(i + 76, b64.length())).append("\r\n");
            }
            sendData(c, msg.toString());
            sendLine(c, ".");
            expect(c, 250);
            sendLine(c, "QUIT");
            return messageId;
        } catch (MailException e) {
            throw e;
        } catch (Exception e) {
            log.debug("SMTP 发送异常: {}", e.getClass().getSimpleName());
            throw new MailException("发送邮件失败");
        } finally {
            if (opened) {
                try { c.socket.close(); } catch (Exception ignored) { }
            }
        }
    }

    private static final class Conn {
        SSLSocket socket;
        InputStream in;
        OutputStream out;
    }

    private void sendLine(Conn c, String s) throws IOException {
        c.out.write((s + "\r\n").getBytes(StandardCharsets.UTF_8));
        c.out.flush();
    }

    private void sendData(Conn c, String data) throws IOException {
        String[] lines = data.split("\r\n", -1);
        for (String line : lines) {
            if (line.startsWith(".")) line = "." + line; // dot-stuffing
            c.out.write((line + "\r\n").getBytes(StandardCharsets.UTF_8));
        }
        c.out.flush();
    }

    private String readLine(Conn c) {
        try {
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            int b;
            while ((b = c.in.read()) != -1) {
                if (b == '\n') break;
                if (b == '\r') continue;
                buf.write(b);
            }
            if (b == -1 && buf.size() == 0) return null;
            return new String(buf.toByteArray(), StandardCharsets.ISO_8859_1);
        } catch (IOException e) {
            throw new MailException("SMTP 读取中断");
        }
    }

    /**
     * 读取一个完整 SMTP 应答并断言码值（RFC 5321：{@code 250-…} 为续行、{@code 250 …} 为末行）。
     * QQ 服务器的 250 应答是多行的（首行 {@code 250-hostname}），此前按「空格分隔单行」解析，
     * {@code expect(250)} 遇到 {@code 250-newx…qq.com} 直接判「SMTP 响应异常」——
     * 现象是 AUTH/MAIL FROM 阶段必失败。故 expect 与 expectMultiline 统一为多行循环。
     */
    private void expect(Conn c, int code) {
        while (true) {
            String line = readLine(c);
            if (line == null) throw new MailException("SMTP 连接中断");
            if (line.length() < 3) throw new MailException("SMTP 响应异常：" + line);
            int got;
            try { got = Integer.parseInt(line.substring(0, 3)); } catch (Exception e) { throw new MailException("SMTP 响应异常：" + line); }
            if (got != code) throw new MailException("SMTP 错误 " + got + "：" + line.substring(Math.min(4, line.length())).trim());
            if (line.length() <= 3 || line.charAt(3) != '-') break;   // 末行（空格或裸码）⇒ 应答结束
        }
    }

    private boolean hasCrlf(String s) {
        return s != null && CRLF.matcher(s).find();
    }

    private List<String> splitAddrs(String s) {
        List<String> out = new ArrayList<>();
        for (String a : s.split("[,;\\s]+")) {
            if (!a.isBlank()) out.add(a.trim());
        }
        return out;
    }

    private String rfcDate() {
        return new java.text.SimpleDateFormat("EEE, dd MMM yyyy HH:mm:ss Z", Locale.US).format(new Date());
    }
}
