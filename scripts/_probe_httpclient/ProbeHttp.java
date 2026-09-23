import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * 复刻 WorkerScheduleService.callAgentComplete 的 HttpClient 用法，打指定目标。
 * 用法: java ProbeHttp.java <host> <port> [h11|h2|h2c]
 *   h11 = 请求级强制 HTTP/1.1
 *   h2c = 请求级强制 HTTP/1.1（对照 h11 应为同一行为）
 */
public class ProbeHttp {
    public static void main(String[] args) throws Exception {
        String host = args.length > 0 ? args[0] : "127.0.0.1";
        int port = args.length > 1 ? Integer.parseInt(args[1]) : 8000;
        String mode = args.length > 2 ? args[2] : "default";

        HttpClient.Builder cb = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5));
        // ch11 = 客户端级强制 HTTP/1.1（本次修复采用的形式）
        if (mode.equals("ch11")) {
            cb.version(HttpClient.Version.HTTP_1_1);
        }
        HttpClient http = cb.build();

        String body = "{\"prompt\":\"hi\",\"system\":\"s\",\"max_tokens\":16}";
        HttpRequest.Builder rb = HttpRequest.newBuilder()
                .uri(URI.create("http://" + host + ":" + port + "/internal/v1/complete"))
                .timeout(Duration.ofSeconds(10))
                .header("Content-Type", "application/json");
        if (mode.equals("h11")) {
            rb.version(HttpClient.Version.HTTP_1_1);
        }
        HttpRequest req = rb.POST(HttpRequest.BodyPublishers.ofString(body)).build();

        try {
            HttpResponse<String> r = http.send(req, HttpResponse.BodyHandlers.ofString());
            String b = r.body() == null ? "" : r.body().replace("\n", " ");
            if (b.length() > 160) b = b.substring(0, 160) + "...";
            System.out.println("RESULT mode=" + mode + " status=" + r.statusCode() + " body=" + b);
        } catch (Exception e) {
            System.out.println("RESULT mode=" + mode + " EX " + e);
        }
    }
}
