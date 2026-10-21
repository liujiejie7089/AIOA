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
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 纯 JDK IMAP 客户端（imap.qq.com:993 SSL，连接 6s / 读 15s）。不引入任何第三方库，
 * 沿用 {@code QqMailProbe} 的「手写 TLS 文本协议」风格。
 *
 * <p><b>关键纪律</b>：</p>
 * <ul>
 *   <li>读信一律 {@code EXAMINE} + {@code BODY.PEEK[...]}，<b>绝不</b>置 {@code \Seen}；</li>
 *   <li>FETCH 的 {@code {N}} 字面量按<b>字节精确</b>读取，不按行读（最易错处）；</li>
 *   <li>MIME 头解码支持 {@code =?UTF-8?B?...?=} / {@code =?GBK?B?...?=}，折行头先拼接；</li>
 *   <li>异常收敛为 {@link MailException}（中文原因，<b>不含凭据</b>）；日志不打印授权码。</li>
 * </ul>
 *
 * <p>解析方法（{@code parseXxx}）为包级可见，便于无网络的字面量解析单测直接驱动。</p>
 */
@Slf4j
@Component
public class ImapClient {

    private static final String HOST = "imap.qq.com";
    private static final int PORT = 993;
    private static final int CONNECT_TIMEOUT_MS = 6000;
    private static final int READ_TIMEOUT_MS = 15000;

    /** FETCH 响应里那一段原始头字节（解析用），对外输出前会被摘掉，见 parseFetchHeaders。 */
    private static final String KEY_RAW = "__rawHeaders";

    /** 行尾的 {@code {N}} 字面量标记。 */
    private static final Pattern LITERAL = Pattern.compile("\\{(\\d+)\\}\\s*$");
    private static final Pattern UID_PAT = Pattern.compile("\\bUID\\s+(\\d+)");
    private static final Pattern SIZE_PAT = Pattern.compile("\\bRFC822\\.SIZE\\s+(\\d+)");
    private static final Pattern FLAGS_PAT = Pattern.compile("FLAGS\\s*\\(([^)]*)\\)");
    private static final Pattern INTERNALDATE_PAT = Pattern.compile("INTERNALDATE\\s+\"([^\"]*)\"");
    private static final Pattern LIST_PAT = Pattern.compile(
            "^\\* LIST\\s+\\(([^)]*)\\)\\s+(\"[^\"]*\"|NIL)\\s+(\"[^\"]*\"|NIL)\\s*$");
    private static final Pattern ENCODED_WORD = Pattern.compile("=\\?([A-Za-z0-9_-]+)\\?([BbQq])\\?([^?]*)\\?=");

    // ---------------------------------------------------------------- 对外 API

    public List<Map<String, Object>> listFolders(String email, String authCode) {
        return withSession(email, authCode, c -> {
            ImapResponse resp = command(c, "LIST \"\" \"*\"");
            if (!resp.ok()) throw new MailException("获取邮箱目录失败：" + resp.text);
            return parseListFolders(resp);
        });
    }

    public List<Map<String, Object>> listMessages(String email, String authCode,
                                                 String folder, int limit, boolean unreadOnly) {
        return withSession(email, authCode, c -> {
            examine(c, folder);
            List<Long> uids = searchUids(c, unreadOnly);
            if (uids.isEmpty()) return Collections.emptyList();
            int from = Math.max(0, uids.size() - limit);
            String set = String.join(",", uids.subList(from, uids.size()).stream().map(String::valueOf).toList());
            ImapResponse resp = command(c, "UID FETCH " + set
                    + " (UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])");
            if (!resp.ok()) throw new MailException("读取邮件列表失败：" + resp.text);
            List<Map<String, Object>> recs = parseFetchHeaders(resp);
            Collections.reverse(recs); // 最新在前
            return recs;
        });
    }

    public Map<String, Object> readMessage(String email, String authCode, long uid, String folder) {
        return withSession(email, authCode, c -> {
            examine(c, folder);
            ImapResponse resp = command(c, "UID FETCH " + uid + " (UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[])");
            if (!resp.ok()) throw new MailException("读取邮件失败：" + resp.text);
            return parseFetchBody(resp, uid);
        });
    }

    public List<Map<String, Object>> searchMessages(String email, String authCode,
                                                   String query, String folder, int limit) {
        return withSession(email, authCode, c -> {
            examine(c, folder);
            ImapResponse resp = command(c, "UID SEARCH TEXT " + quote(query));
            if (!resp.ok()) throw new MailException("搜索邮件失败：" + resp.text);
            List<Long> uids = parseSearch(resp);
            if (uids.isEmpty()) return Collections.emptyList();
            int from = Math.max(0, uids.size() - limit);
            String set = String.join(",", uids.subList(from, uids.size()).stream().map(String::valueOf).toList());
            ImapResponse fr = command(c, "UID FETCH " + set
                    + " (UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])");
            if (!fr.ok()) throw new MailException("读取搜索结果失败：" + fr.text);
            List<Map<String, Object>> recs = parseFetchHeaders(fr);
            Collections.reverse(recs);
            return recs;
        });
    }

    // ------------------------------------------------------------ 会话与传输层

    @FunctionalInterface
    private interface SessionFn<T> {
        T apply(Conn c) throws Exception;
    }

    private static final class Conn {
        SSLSocket socket;
        InputStream in;
        OutputStream out;
        int tag = 0;
    }

    private <T> T withSession(String email, String authCode, SessionFn<T> fn) {
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
            String greet = readLine(c);
            if (greet == null || !greet.startsWith("* OK")) throw new MailException("IMAP 服务握手失败");
            login(c, email, authCode);
            return fn.apply(c);
        } catch (MailException e) {
            throw e;
        } catch (Exception e) {
            log.debug("IMAP 会话异常: {}", e.getClass().getSimpleName());
            throw new MailException("连接 QQ 邮箱失败");
        } finally {
            if (opened) {
                try { writeLine(c, "a" + (++c.tag) + " LOGOUT"); } catch (Exception ignored) { }
                try { c.socket.close(); } catch (Exception ignored) { }
            }
        }
    }

    private void login(Conn c, String email, String authCode) {
        ImapResponse r = command(c, "LOGIN " + quote(email) + " " + quote(authCode));
        if (!r.ok()) throw new MailException("QQ 邮箱登录失败：" + r.text);
    }

    private void examine(Conn c, String folder) {
        ImapResponse r = command(c, "EXAMINE " + quote(folder));
        if (!r.ok()) throw new MailException("无法打开邮箱目录：" + r.text);
    }

    private List<Long> searchUids(Conn c, boolean unreadOnly) {
        ImapResponse r = command(c, "UID SEARCH " + (unreadOnly ? "UNSEEN" : "ALL"));
        if (!r.ok()) throw new MailException("检索邮件失败：" + r.text);
        return parseSearch(r);
    }

    /** 通用命令：写出 cmd，逐行读取直到 {@code <tag> OK/NO/BAD}；遇 {@code {N}} 字面量按字节读入。 */
    private ImapResponse command(Conn c, String cmd) {
        String tag = "a" + (++c.tag);
        writeLine(c, tag + " " + cmd);
        List<Object> parts = new ArrayList<>();
        String completion = null;
        while (true) {
            String line = readLine(c);
            if (line == null) throw new MailException("IMAP 连接中断");
            parts.add(line);
            Matcher m = LITERAL.matcher(line);
            if (m.find()) {
                int n = Integer.parseInt(m.group(1));
                parts.add(readLiteral(c, n));
            }
            if (line.startsWith(tag + " ")) {
                completion = line;
                break;
            }
        }
        String status = "BAD";
        String text = "";
        if (completion != null) {
            String rest = completion.substring(tag.length()).trim();
            if (rest.startsWith("OK")) status = "OK";
            else if (rest.startsWith("NO")) status = "NO";
            else if (rest.startsWith("BAD")) status = "BAD";
            text = rest.replaceFirst("^(OK|NO|BAD)\\s*", "");
        }
        return new ImapResponse(status, text, parts);
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
            throw new MailException("IMAP 读取中断");
        }
    }

    /** 按字节精确读取 N 字面量，再消费其后的行结束符（CRLF / LF）。 */
    private byte[] readLiteral(Conn c, int n) {
        try {
            byte[] buf = new byte[n];
            int off = 0;
            while (off < n) {
                int r = c.in.read(buf, off, n - off);
                if (r == -1) throw new MailException("IMAP 响应字面量被截断");
                off += r;
            }
            int b = c.in.read();
            if (b == '\r') b = c.in.read();
            while (b != -1 && b != '\n') b = c.in.read();
            return buf;
        } catch (IOException e) {
            throw new MailException("IMAP 读取中断");
        }
    }

    private void writeLine(Conn c, String s) {
        try {
            c.out.write((s + "\r\n").getBytes(StandardCharsets.UTF_8));
            c.out.flush();
        } catch (IOException e) {
            throw new MailException("IMAP 写入失败");
        }
    }

    // ---------------------------------------------------------------- 解析层

    List<Map<String, Object>> parseListFolders(ImapResponse resp) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Object p : resp.parts) {
            if (!(p instanceof String line)) continue;
            Matcher m = LIST_PAT.matcher(line);
            if (m.find()) {
                Map<String, Object> map = new LinkedHashMap<>();
                String fl = m.group(1).trim();
                map.put("flags", fl.isEmpty() ? Collections.emptyList() : Arrays.asList(fl.split("\\s+")));
                String delim = m.group(2);
                map.put("delimiter", "NIL".equals(delim) ? null : unquote(delim));
                String name = m.group(3);
                map.put("name", "NIL".equals(name) ? "" : unquote(name));
                out.add(map);
            }
        }
        return out;
    }

    List<Map<String, Object>> parseFetchHeaders(ImapResponse resp) {
        List<Map<String, Object>> out = new ArrayList<>();
        Map<String, Object> cur = null;
        for (Object p : resp.parts) {
            if (p instanceof String line) {
                if (line.startsWith("* ") && line.contains("FETCH")) {
                    cur = new LinkedHashMap<>();
                    cur.put("uid", firstLong(UID_PAT, line));
                    cur.put("size", firstLong(SIZE_PAT, line));
                    cur.put("date", firstGroup(INTERNALDATE_PAT, line));
                    String fl = firstGroup(FLAGS_PAT, line);
                    boolean seen = fl != null && fl.contains("\\Seen");
                    cur.put("unread", !seen);
                    cur.put("flags", fl == null ? Collections.emptyList()
                            : Arrays.asList(fl.trim().split("\\s+")));
                    cur.put(KEY_RAW, null);
                    out.add(cur);
                }
            } else if (p instanceof byte[] b) {
                if (cur != null && cur.get(KEY_RAW) == null) {
                    cur.put(KEY_RAW, b);
                    Map<String, String> hdr = parseHeaders(b);
                    cur.put("from", hdr.get("from"));
                    cur.put("to", hdr.get("to"));
                    cur.put("subject", hdr.get("subject"));
                    cur.put("messageId", hdr.get("message-id"));
                    if (cur.get("date") == null) cur.put("date", hdr.get("date"));
                }
            }
        }
        // 原始头字节只用来解析，不对外暴露：Jackson 会把 byte[] 编码成 base64，
        // 每条消息多出几百字节不可读的噪声（模型读到的就是一串 base64），故解析完即摘掉。
        for (Map<String, Object> m : out) m.remove(KEY_RAW);
        return out;
    }

    Map<String, Object> parseFetchBody(ImapResponse resp, long uid) {
        byte[] raw = null;
        for (Object p : resp.parts) {
            if (p instanceof byte[] b) { raw = b; break; }
        }
        if (raw == null) throw new MailException("读取邮件正文失败");
        Map<String, String> hdr = parseHeaders(raw);
        Map<String, Object> rec = new LinkedHashMap<>();
        rec.put("uid", uid);
        rec.put("from", hdr.get("from"));
        rec.put("to", hdr.get("to"));
        rec.put("subject", hdr.get("subject"));
        rec.put("date", hdr.get("date"));
        rec.put("body", extractPlainText(raw));
        return rec;
    }

    private List<Long> parseSearch(ImapResponse resp) {
        List<Long> uids = new ArrayList<>();
        for (Object p : resp.parts) {
            if (p instanceof String line && line.startsWith("* SEARCH")) {
                String[] tok = line.substring(8).trim().split("\\s+");
                for (String t : tok) {
                    try { uids.add(Long.parseLong(t)); } catch (Exception ignored) { }
                }
            }
        }
        return uids;
    }

    Map<String, String> parseHeaders(byte[] raw) {
        String text = new String(raw, StandardCharsets.UTF_8).replaceAll("\r?\n[ \t]+", " ");
        Map<String, String> map = new LinkedHashMap<>();
        for (String line : text.split("\r?\n")) {
            int idx = line.indexOf(':');
            if (idx <= 0) continue;
            String key = line.substring(0, idx).trim().toLowerCase();
            String val = line.substring(idx + 1).trim();
            map.putIfAbsent(key, decodeHeader(val));
        }
        return map;
    }

    /** 从整封（BODY.PEEK[] 取回的）RFC822 报文里抽取纯文本正文。包级可见：供无网络的解析单测驱动。 */
    String extractPlainText(byte[] raw) {
        try {
            String full = new String(raw, StandardCharsets.ISO_8859_1);
            int sep = full.indexOf("\r\n\r\n");
            int sepLen = 4;
            if (sep < 0) { sep = full.indexOf("\n\n"); sepLen = 2; }
            String headerStr = sep >= 0 ? full.substring(0, sep) : full;
            String bodyStr = sep >= 0 ? full.substring(sep + sepLen) : "";
            // ★ 折行头必须先拼回一行再取字段。RFC5322 允许 header 用 CRLF + 空白（空格/Tab）续行，
            //   QQ / 钉钉这类 MUA 就会把 Content-Type 折成：
            //       Content-Type: multipart/alternative;
            //            boundary="----=_Part_4820_..."
            //   而 headerField 的正则用 `(.*)$`（`.` 不跨行）⇒ 只拿到 "multipart/alternative; "，
            //   boundary 丢失 ⇒ extractFromMultipart 拿到 null 直接返回 ""，
            //   现象就是 read_message 的 body 恒为空串（邮件能列出、能看标题，点进去没正文）。
            String headers = unfold(headerStr);
            String ct = headerField(headers, "Content-Type");
            if (ct.toLowerCase().contains("multipart")) {
                return extractFromMultipart(bodyStr, boundaryOf(ct));
            }
            String te = headerField(headers, "Content-Transfer-Encoding");
            return decodeBodyPart(bodyStr, te, charsetOf(ct));
        } catch (Exception e) {
            return "";
        }
    }

    private String extractFromMultipart(String bodyStr, String boundary) {
        if (boundary == null) return "";
        String[] parts = bodyStr.split("--" + Pattern.quote(boundary), -1);
        String plain = null, html = null;
        for (String part : parts) {
            if (part.startsWith("--")) continue;
            part = part.replaceFirst("^\\r?\\n", "");
            int idx = part.indexOf("\r\n\r\n");
            int l = 4;
            if (idx < 0) { idx = part.indexOf("\n\n"); l = 2; }
            if (idx < 0) continue;
            // 每个 part 的头也可能折行（内层 part 的 Content-Type 同样会出现 `;\r\n\tboundary=`）
            String ph = unfold(part.substring(0, idx));
            String pb = part.substring(idx + l);
            String ct = headerField(ph, "Content-Type").toLowerCase();
            String te = headerField(ph, "Content-Transfer-Encoding");
            if (ct.contains("text/plain") && plain == null) {
                plain = decodeBodyPart(pb, te, charsetOf(headerField(ph, "Content-Type")));
            } else if (ct.contains("text/html") && html == null) {
                html = decodeBodyPart(pb, te, charsetOf(headerField(ph, "Content-Type")));
            }
        }
        // 纯文本段经常只是「你的客户端不支持 HTML」这类占位（钉钉等国内 MUA 的常见写法，
        // 实测只有 48 字节），直接返回它等于让读信正文变成一句废话。占位时改用 HTML 段。
        if (plain != null && !isStubPlain(plain)) return plain;
        if (html != null) {
            String text = stripHtml(html);
            if (!text.isBlank()) return text;
        }
        return plain == null ? "" : plain;
    }

    /**
     * 判断 text/plain 段是否只是「不支持 HTML」的占位文本。
     *
     * <p>只对<b>短</b>文本做判断（超过 120 字符一律当真正文），避免把正常的简短邮件误判掉。</p>
     */
    private boolean isStubPlain(String s) {
        String t = s.replaceAll("\\s+", " ").trim().toLowerCase();
        if (t.isEmpty()) return true;
        if (t.length() > 120) return false;
        return t.contains("does not support html")
                || t.contains("不支持 html") || t.contains("不支持html")
                || t.contains("cannot display html")
                || t.contains("无法显示 html") || t.contains("无法显示html");
    }

    private String decodeBodyPart(String content, String te, String charset) {
        if (te != null && te.toLowerCase().contains("base64")) {
            byte[] data = Base64.getDecoder().decode(content.replaceAll("\\s+", "")
                    .getBytes(StandardCharsets.ISO_8859_1));
            return new String(data, safeCharset(charset));
        }
        if (te != null && te.toLowerCase().contains("quoted-printable")) {
            byte[] data = qpDecodeBytes(content);
            return new String(data, safeCharset(charset));
        }
        return new String(content.trim().getBytes(StandardCharsets.ISO_8859_1), safeCharset(charset));
    }

    private String decodeHeader(String v) {
        if (v == null) return null;
        Matcher m = ENCODED_WORD.matcher(v);
        StringBuffer sb = new StringBuffer();
        while (m.find()) {
            String charset = m.group(1);
            String enc = m.group(2).toUpperCase();
            String data = m.group(3);
            String decoded;
            try {
                if ("B".equals(enc)) {
                    decoded = new String(Base64.getDecoder().decode(data), safeCharset(charset));
                } else {
                    decoded = qDecode(data, charset);
                }
            } catch (Exception e) {
                decoded = m.group(0);
            }
            m.appendReplacement(sb, Matcher.quoteReplacement(decoded));
        }
        m.appendTail(sb);
        return sb.toString();
    }

    private String qDecode(String s, String charset) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            if (ch == '_') {
                out.write(' ');
            } else if (ch == '=' && i + 2 < s.length()) {
                int hi = Character.digit(s.charAt(i + 1), 16);
                int lo = Character.digit(s.charAt(i + 2), 16);
                if (hi >= 0 && lo >= 0) { out.write((hi << 4) | lo); i += 2; }
                else out.write(ch);
            } else {
                out.write(ch);
            }
        }
        return new String(out.toByteArray(), safeCharset(charset));
    }

    private byte[] qpDecodeBytes(String content) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] bytes = content.getBytes(StandardCharsets.ISO_8859_1);
        int i = 0;
        while (i < bytes.length) {
            int b = bytes[i] & 0xff;
            if (b == '=' && i + 2 < bytes.length) {
                int hi = hex(bytes[i + 1]);
                int lo = hex(bytes[i + 2]);
                if (hi >= 0 && lo >= 0) { out.write((hi << 4) | lo); i += 3; continue; }
                if (bytes[i + 1] == '\r' && bytes[i + 2] == '\n') { i += 3; continue; }
            }
            if (b != '\r' && b != '\n') out.write(b);
            i++;
        }
        return out.toByteArray();
    }

    private static int hex(int b) {
        if (b >= '0' && b <= '9') return b - '0';
        if (b >= 'a' && b <= 'f') return b - 'a' + 10;
        if (b >= 'A' && b <= 'F') return b - 'A' + 10;
        return -1;
    }

    private String headerField(String block, String name) {
        Matcher m = Pattern.compile("(?im)^" + Pattern.quote(name) + "\\s*:\\s*(.*)$").matcher(block);
        return m.find() ? m.group(1).trim() : "";
    }

    /**
     * 展开折行头（header folding）：把 {@code CRLF + 空格/Tab} 续行拼回同一行。
     *
     * <p>不做这一步，任何跨行的 header 都只会被读到第一行（见 extractPlainText 里的说明）。
     * 只用于解析、不用于改写报文，故直接对视图做替换即可。</p>
     */
    private String unfold(String block) {
        return block == null ? "" : block.replaceAll("\r?\n[ \t]+", " ");
    }

    private String boundaryOf(String ct) {
        Matcher m = Pattern.compile("(?i)boundary=\"?([^\";]+)\"?").matcher(ct);
        return m.find() ? m.group(1).trim() : null;
    }

    private String charsetOf(String ct) {
        Matcher m = Pattern.compile("(?i)charset=\"?([^\";]+)\"?").matcher(ct);
        return m.find() ? m.group(1).trim() : "UTF-8";
    }

    private Charset safeCharset(String cs) {
        try { return Charset.forName(cs); } catch (Exception e) { return StandardCharsets.UTF_8; }
    }

    private String stripHtml(String html) {
        return html.replaceAll("(?is)<style[^>]*>.*?</style>", " ")
                .replaceAll("(?is)<script[^>]*>.*?</script>", " ")
                .replaceAll("(?is)<[^>]+>", " ")
                .replaceAll("\\s+", " ").trim();
    }

    private String firstGroup(Pattern p, String s) {
        Matcher m = p.matcher(s);
        return m.find() ? m.group(1) : null;
    }

    private long firstLong(Pattern p, String s) {
        Matcher m = p.matcher(s);
        return m.find() ? Long.parseLong(m.group(1)) : 0L;
    }

    private static String unquote(String s) {
        if (s == null) return "";
        if (s.length() >= 2 && s.startsWith("\"") && s.endsWith("\"")) return s.substring(1, s.length() - 1);
        return s;
    }

    /** IMAP 参数引号/反斜杠转义（与 QqMailProbe.quote 同口径）。 */
    static String quote(String s) {
        String escaped = s.replace("\\", "\\\\").replace("\"", "\\\"");
        return "\"" + escaped + "\"";
    }

    /** 命令响应容器（包级可见，便于单测）。 */
    static final class ImapResponse {
        final String status;
        final String text;
        final List<Object> parts;

        ImapResponse(String status, String text, List<Object> parts) {
            this.status = status;
            this.text = text;
            this.parts = parts;
        }

        boolean ok() {
            return "OK".equals(status);
        }
    }
}
