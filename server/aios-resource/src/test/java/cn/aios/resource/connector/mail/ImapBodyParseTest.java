package cn.aios.resource.connector.mail;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.Base64;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 正文解析的字面量单测（无网络、无凭据）。
 *
 * <p><b>为什么必须有这条</b>：QQ / 钉钉这类 MUA 会把 {@code Content-Type} 折行写成
 * {@code multipart/alternative;} 换行 {@code \tboundary="..."}。而取头用的是
 * {@code ^Name\s*:\s*(.*)$}（{@code .} 不跨行）⇒ 只拿到 {@code "multipart/alternative; "}，
 * boundary 丢失 ⇒ {@code extractFromMultipart} 拿到 null 立刻返回空串。
 *
 * <p>线上现象极具迷惑性：邮件列表正常（from/subject/date 都解析对）、点开却<b>没有正文</b>，
 * 且不报错（{@code extractPlainText} 的 catch 把异常吞成空串）。所以这里锁死「折行头」这一例。</p>
 */
class ImapBodyParseTest {

    private final ImapClient client = new ImapClient();

    private static String b64(String s) {
        return Base64.getEncoder().encodeToString(s.getBytes(StandardCharsets.UTF_8));
    }

    /** 折行的 Content-Type（与线上 QQ 邮件同形）。 */
    @Test
    @DisplayName("折行的 multipart Content-Type：body 不能为空")
    void foldedContentTypeMultipart() {
        String raw = "Date: Thu, 21 Jul 2022 19:26:29 +0800 (CST)\r\n"
                + "From: =?UTF-8?B?" + b64("钉钉帐号安全团队") + "?= <no-reply@accounts.dingtalk.com>\r\n"
                + "To: \"3260791262@qq.com\" <3260791262@qq.com>\r\n"
                + "Subject: =?UTF-8?B?" + b64("钉钉验证码") + "?=\r\n"
                + "Content-Type: multipart/alternative;\r\n"
                + "\tboundary=\"----=_Part_4820_1840945558.1658402789461\"\r\n"
                + "MIME-Version: 1.0\r\n"
                + "\r\n"
                + "------=_Part_4820_1840945558.1658402789461\r\n"
                + "Content-Type: text/plain; charset=utf-8\r\n"
                + "Content-Transfer-Encoding: base64\r\n"
                + "\r\n"
                + b64("你的验证码是 123456") + "\r\n"
                + "------=_Part_4820_1840945558.1658402789461\r\n"
                + "Content-Type: text/html; charset=utf-8\r\n"
                + "Content-Transfer-Encoding: base64\r\n"
                + "\r\n"
                + b64("<p>你的验证码是 123456</p>") + "\r\n"
                + "------=_Part_4820_1840945558.1658402789461--\r\n";

        String body = client.extractPlainText(raw.getBytes(StandardCharsets.UTF_8));
        assertFalse(body.isEmpty(), "折行头下 body 不能是空串（这正是线上 read_message 无正文的原因）");
        assertTrue(body.contains("123456"), "正文应包含验证码，实际=" + body);
    }

    /** 同一封邮件的 Content-Type 若写成一行（未折行），旧实现本来就能过——防回归。 */
    @Test
    @DisplayName("未折行的 multipart Content-Type：仍然正常")
    void singleLineContentTypeMultipart() {
        String raw = "Content-Type: multipart/alternative; boundary=\"b1\"\r\n"
                + "\r\n"
                + "--b1\r\n"
                + "Content-Type: text/plain; charset=utf-8\r\n"
                + "Content-Transfer-Encoding: base64\r\n"
                + "\r\n"
                + b64("单行头也应该能解析") + "\r\n"
                + "--b1--\r\n";

        String body = client.extractPlainText(raw.getBytes(StandardCharsets.UTF_8));
        assertTrue(body.contains("单行头也应该能解析"), "实际=" + body);
    }

    /** 非 multipart：单段 base64 正文。 */
    @Test
    @DisplayName("单段 base64 正文")
    void singlePartBase64() {
        String raw = "Content-Type: text/plain; charset=utf-8\r\n"
                + "Content-Transfer-Encoding: base64\r\n"
                + "\r\n"
                + b64("纯文本一段") + "\r\n";

        assertEquals("纯文本一段", client.extractPlainText(raw.getBytes(StandardCharsets.UTF_8)).trim());
    }

    /**
     * text/plain 只是「不支持 HTML」的占位时，正文必须回退到 HTML 段。
     *
     * <p>线上实例：钉钉验证码邮件的 text/plain 就是 48 字节的
     * "Your email client does not support HTML messages"，真正的验证码只在 HTML 里。</p>
     */
    @Test
    @DisplayName("纯文本是占位 → 回退取 HTML 正文")
    void stubPlainFallsBackToHtml() {
        String raw = "Content-Type: multipart/alternative;\r\n"
                + " boundary=\"b2\"\r\n"
                + "\r\n"
                + "--b2\r\n"
                + "Content-Type: text/plain; charset=utf-8\r\n"
                + "\r\n"
                + "Your email client does not support HTML messages\r\n"
                + "--b2\r\n"
                + "Content-Type: text/html; charset=utf-8\r\n"
                + "\r\n"
                + "<p>验证码 <b>4168</b></p>\r\n"
                + "--b2--\r\n";

        String body = client.extractPlainText(raw.getBytes(StandardCharsets.UTF_8));
        assertTrue(body.contains("4168"), "应回退到 HTML 段拿到验证码，实际=" + body);
        assertFalse(body.contains("does not support HTML"), "不应把占位句当正文，实际=" + body);
    }
}
