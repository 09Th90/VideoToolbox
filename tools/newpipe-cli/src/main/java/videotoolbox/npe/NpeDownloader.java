package videotoolbox.npe;

import org.schabi.newpipe.extractor.downloader.Request;
import org.schabi.newpipe.extractor.downloader.Response;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ProxySelector;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * NewPipe Extractor 的 {@link org.schabi.newpipe.extractor.downloader.Downloader} 实现。
 *
 * <p>只用 JDK 内置的 java.net.http.HttpClient，不引入 okhttp，
 * 这样整个 CLI 的依赖树保持极小、便于打包分发。
 */
public class NpeDownloader extends org.schabi.newpipe.extractor.downloader.Downloader {

    /** 桌面浏览器 UA：YouTube 对空 UA / java UA 的返回内容不同，会影响格式列表。 */
    public static final String DEFAULT_UA =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            + "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

    private final HttpClient client;
    private final String cookie;
    private final int timeoutSec;

    public NpeDownloader(String proxy, String cookie, int timeoutSec) {
        this.cookie = cookie == null ? "" : cookie.trim();
        this.timeoutSec = timeoutSec > 0 ? timeoutSec : 30;

        HttpClient.Builder b = HttpClient.newBuilder()
                .followRedirects(HttpClient.Redirect.NORMAL)
                .connectTimeout(Duration.ofSeconds(this.timeoutSec));
        if (proxy != null && !proxy.isEmpty()) {
            String p = proxy.startsWith("http") ? proxy.substring(proxy.indexOf("://") + 3) : proxy;
            String host = p;
            int port = 80;
            int idx = p.lastIndexOf(':');
            if (idx > 0) {
                host = p.substring(0, idx);
                port = Integer.parseInt(p.substring(idx + 1).replace("/", ""));
            }
            b.proxy(ProxySelector.of(new InetSocketAddress(host, port)));
        }
        this.client = b.build();
    }

    @Override
    public Response execute(Request request) throws IOException {
        String method = request.httpMethod() == null ? "GET" : request.httpMethod().toUpperCase(Locale.ROOT);
        Map<String, List<String>> reqHeaders = request.headers();

        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(request.url()))
                .timeout(Duration.ofSeconds(timeoutSec));

        boolean hasUa = false;
        boolean hasCookie = false;
        if (reqHeaders != null) {
            for (Map.Entry<String, List<String>> e : reqHeaders.entrySet()) {
                String k = e.getKey();
                if (k == null || e.getValue() == null) {
                    continue;
                }
                if (k.equalsIgnoreCase("User-Agent")) {
                    hasUa = true;
                }
                if (k.equalsIgnoreCase("Cookie")) {
                    hasCookie = true;
                }
                for (String v : e.getValue()) {
                    if (v != null) {
                        b.header(k, v);
                    }
                }
            }
        }
        if (!hasUa) {
            b.header("User-Agent", DEFAULT_UA);
        }
        if (!hasCookie && !cookie.isEmpty()) {
            b.header("Cookie", cookie);
        }
        b.header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8");

        byte[] body = request.dataToSend();
        switch (method) {
            case "HEAD":
                b.method("HEAD", HttpRequest.BodyPublishers.noBody());
                break;
            case "POST":
                b.POST(HttpRequest.BodyPublishers.ofByteArray(body == null ? new byte[0] : body));
                break;
            case "DELETE":
                b.method("DELETE", HttpRequest.BodyPublishers.ofByteArray(body == null ? new byte[0] : body));
                break;
            case "PUT":
                b.PUT(HttpRequest.BodyPublishers.ofByteArray(body == null ? new byte[0] : body));
                break;
            case "GET":
            default:
                b.GET();
                break;
        }

        HttpResponse<byte[]> resp;
        try {
            resp = client.send(b.build(), HttpResponse.BodyHandlers.ofByteArray());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("请求被中断: " + request.url(), e);
        }

        Map<String, List<String>> respHeaders = new java.util.LinkedHashMap<>();
        resp.headers().map().forEach((k, v) -> respHeaders.put(k, new ArrayList<>(v)));

        String charsetName = resp.headers().firstValue("Content-Type")
                .map(NpeDownloader::charsetFromContentType)
                .orElse(null);
        Charset cs = StandardCharsets.UTF_8;
        if (charsetName != null) {
            try {
                cs = Charset.forName(charsetName);
            } catch (Exception ignored) {
                cs = StandardCharsets.UTF_8;
            }
        }

        return new Response(resp.statusCode(), "", respHeaders,
                new String(resp.body(), cs), resp.uri().toString());
    }

    private static String charsetFromContentType(String ct) {
        int i = ct.toLowerCase(Locale.ROOT).indexOf("charset=");
        if (i < 0) {
            return null;
        }
        String v = ct.substring(i + 8).trim();
        int sep = v.indexOf(';');
        if (sep >= 0) {
            v = v.substring(0, sep);
        }
        return v.replace("\"", "").trim();
    }
}
