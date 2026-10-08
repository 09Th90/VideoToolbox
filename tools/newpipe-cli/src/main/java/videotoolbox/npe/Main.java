package videotoolbox.npe;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.schabi.newpipe.extractor.NewPipe;
import org.schabi.newpipe.extractor.StreamingService;
import org.schabi.newpipe.extractor.exceptions.ContentNotAvailableException;
import org.schabi.newpipe.extractor.exceptions.ExtractionException;
import org.schabi.newpipe.extractor.exceptions.ReCaptchaException;
import org.schabi.newpipe.extractor.localization.Localization;
import org.schabi.newpipe.extractor.stream.AudioStream;
import org.schabi.newpipe.extractor.stream.Stream;
import org.schabi.newpipe.extractor.stream.StreamInfo;
import org.schabi.newpipe.extractor.stream.SubtitlesStream;
import org.schabi.newpipe.extractor.stream.VideoStream;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import java.util.Locale;

/**
 * newpipe-cli：把 NewPipe Extractor 的解析结果以 JSON 打到 stdout，供 Python 侧消费。
 *
 * <p>本 CLI 只负责「解析出流地址」，不负责下载与合流——下载交给 ffmpeg，
 * 这样进度回调、代理、cookie 等策略与视频工具箱现有的下载链路保持一致。
 *
 * <p>退出码：0 成功 / 3 参数错误 / 2 解析失败（风控、下架、网络等）
 */
public class Main {

    public static void main(String[] args) {
        // ⚠️ Windows 上 JVM 的 System.out 默认跟随控制台代码页（GBK）。当 stdout 是
        // 管道（被 Python 调用时）而非控制台时，中文 JSON 会以 GBK 字节输出，
        // 调用方按 UTF-8 解码就得到乱码（实测报错信息变成「利大払移」）。
        // 这里强制 UTF-8，与 Python 侧的解码约定对齐。
        try {
            System.setOut(new java.io.PrintStream(
                    new java.io.FileOutputStream(java.io.FileDescriptor.out), true, "UTF-8"));
            System.setErr(new java.io.PrintStream(
                    new java.io.FileOutputStream(java.io.FileDescriptor.err), true, "UTF-8"));
        } catch (Exception ignored) {
            // 设置失败就退回默认行为，不影响主流程
        }

        String url = null;
        String proxy = null;
        String cookie = null;
        String cookieFile = null;
        int timeout = 30;
        boolean pretty = false;

        for (int i = 0; i < args.length; i++) {
            String a = args[i];
            switch (a) {
                case "--url":
                    url = next(args, ++i);
                    break;
                case "--proxy":
                    proxy = next(args, ++i);
                    break;
                case "--cookie":
                    cookie = next(args, ++i);
                    break;
                case "--cookie-file":
                    cookieFile = next(args, ++i);
                    break;
                case "--timeout":
                    timeout = Integer.parseInt(next(args, ++i));
                    break;
                case "--pretty":
                    pretty = true;
                    break;
                case "-h":
                case "--help":
                    System.out.println("用法: java -jar npe-cli.jar --url <url> "
                            + "[--proxy host:port] [--cookie str] [--cookie-file path] "
                            + "[--timeout sec] [--pretty]");
                    System.exit(0);
                    return;
                default:
                    break;
            }
        }

        if (url == null || url.isEmpty()) {
            System.err.println("缺少 --url");
            System.exit(3);
            return;
        }
        if (cookieFile != null && !cookieFile.isEmpty()) {
            try {
                cookie = loadCookieFile(cookieFile);
            } catch (Exception e) { // noqa
                System.err.println("读取 cookie 文件失败: " + e.getMessage());
            }
        }

        JsonObject out = new JsonObject();
        try {
            NpeDownloader dl = new NpeDownloader(proxy, cookie, timeout);
            NewPipe.init(dl, Localization.fromLocale(Locale.SIMPLIFIED_CHINESE));

            StreamingService svc = NewPipe.getServiceByUrl(url);
            StreamInfo info = StreamInfo.getInfo(svc, url);

            out.addProperty("ok", true);
            out.addProperty("service", svc.getServiceInfo().getName());
            out.addProperty("url", nullToEmpty(info.getUrl()));
            out.addProperty("id", nullToEmpty(info.getId()));
            out.addProperty("title", nullToEmpty(info.getName()));
            out.addProperty("uploader", nullToEmpty(info.getUploaderName()));
            out.addProperty("uploadDate", nullToEmpty(info.getTextualUploadDate()));
            out.addProperty("duration", info.getDuration());
            out.addProperty("viewCount", info.getViewCount());
            out.addProperty("ageLimit", info.getAgeLimit());
            out.addProperty("streamType", String.valueOf(info.getStreamType()));
            out.addProperty("dashMpdUrl", nullToEmpty(info.getDashMpdUrl()));
            out.addProperty("hlsUrl", nullToEmpty(info.getHlsUrl()));
            List<org.schabi.newpipe.extractor.Image> th = info.getThumbnails();
            out.addProperty("thumbnail",
                    (th == null || th.isEmpty()) ? "" : nullToEmpty(th.get(0).getUrl()));

            out.add("videoOnly", streamArray(info.getVideoOnlyStreams()));
            out.add("audioOnly", streamArray(info.getAudioStreams()));
            out.add("muxed", streamArray(info.getVideoStreams()));
            out.add("subtitles", subtitleArray(info.getSubtitles()));
        } catch (ReCaptchaException e) {
            fail(out, "captcha", "触发风控（需要 cookie 或验证码）: " + e.getMessage());
        } catch (ContentNotAvailableException e) {
            fail(out, "unavailable", "内容不可用（下架/地区限制/会员）: " + e.getMessage());
        } catch (ExtractionException e) {
            // NPE 把「IP 被风控」也包在 ExtractionException 里，但消息是
            // "…blocked anonymous watch access with this IP, got error LOGIN_REQUIRED"。
            // 若一律报 extract，上层会误判成"接口变更需升级库"，提示完全跑偏。
            String m = String.valueOf(e.getMessage());
            String low = m.toLowerCase(Locale.ROOT);
            if (low.contains("login_required")
                    || low.contains("sign in to confirm")
                    || low.contains("blocked anonymous")) {
                fail(out, "captcha",
                        "被判定为机器人（需要登录态 cookie 或换出口节点）: " + m);
            } else {
                fail(out, "extract", "解析失败: " + m);
            }
        } catch (IOException e) {
            fail(out, "network", "网络失败: " + e.getMessage());
        } catch (Throwable e) { // noqa: 兜底，保证 JSON 契约
            fail(out, "error", String.valueOf(e.getMessage()));
        }

        Gson gson = pretty ? new GsonBuilder().setPrettyPrinting().create() : new Gson();
        System.out.println(gson.toJson(out));
        System.out.flush();
        if (!out.get("ok").getAsBoolean()) {
            System.exit(2);
        }
    }

    private static void fail(JsonObject out, String type, String msg) {
        out.addProperty("ok", false);
        out.addProperty("errorType", type);
        out.addProperty("error", msg);
        System.err.println("[" + type + "] " + msg);
    }

    private static JsonArray streamArray(List<? extends Stream> streams) {
        JsonArray arr = new JsonArray();
        if (streams == null) {
            return arr;
        }
        for (Stream s : streams) {
            JsonObject o = new JsonObject();
            o.addProperty("url", s.isUrl() ? nullToEmpty(s.getUrl()) : "");
            o.addProperty("content", s.isUrl() ? "" : nullToEmpty(s.getContent()));
            o.addProperty("format",
                    s.getFormat() == null ? "" : nullToEmpty(s.getFormat().getName()));
            o.addProperty("suffix",
                    s.getFormat() == null ? "" : nullToEmpty(s.getFormat().getSuffix()));
            o.addProperty("delivery", String.valueOf(s.getDeliveryMethod()));
            o.addProperty("manifestUrl", nullToEmpty(s.getManifestUrl()));
            if (s instanceof VideoStream) {
                VideoStream v = (VideoStream) s;
                o.addProperty("kind", v.isVideoOnly() ? "video" : "muxed");
                o.addProperty("codec", nullToEmpty(v.getCodec()));
                o.addProperty("resolution", nullToEmpty(v.getResolution()));
                o.addProperty("quality", nullToEmpty(v.getQuality()));
                o.addProperty("width", v.getWidth());
                o.addProperty("height", v.getHeight());
                o.addProperty("fps", v.getFps());
                o.addProperty("bitrate", v.getBitrate());
                o.addProperty("itag", v.getItag());
                o.addProperty("initStart", v.getInitStart());
                o.addProperty("initEnd", v.getInitEnd());
                o.addProperty("indexStart", v.getIndexStart());
                o.addProperty("indexEnd", v.getIndexEnd());
            } else if (s instanceof AudioStream) {
                AudioStream a = (AudioStream) s;
                o.addProperty("kind", "audio");
                o.addProperty("codec", nullToEmpty(a.getCodec()));
                o.addProperty("quality", nullToEmpty(a.getQuality()));
                o.addProperty("bitrate", a.getAverageBitrate() > 0
                        ? a.getAverageBitrate() : a.getBitrate());
                o.addProperty("itag", a.getItag());
                o.addProperty("trackId", nullToEmpty(a.getAudioTrackId()));
                o.addProperty("trackName", nullToEmpty(a.getAudioTrackName()));
                o.addProperty("locale", a.getAudioLocale() == null
                        ? "" : a.getAudioLocale().toLanguageTag());
            } else {
                o.addProperty("kind", "unknown");
            }
            arr.add(o);
        }
        return arr;
    }

    private static JsonArray subtitleArray(List<SubtitlesStream> subs) {
        JsonArray arr = new JsonArray();
        if (subs == null) {
            return arr;
        }
        for (SubtitlesStream s : subs) {
            JsonObject o = new JsonObject();
            o.addProperty("url", s.isUrl() ? nullToEmpty(s.getUrl()) : "");
            o.addProperty("content", s.isUrl() ? "" : nullToEmpty(s.getContent()));
            o.addProperty("format",
                    s.getFormat() == null ? "" : nullToEmpty(s.getFormat().getName()));
            o.addProperty("extension", nullToEmpty(s.getExtension()));
            o.addProperty("languageTag", nullToEmpty(s.getLanguageTag()));
            o.addProperty("displayName", nullToEmpty(s.getDisplayLanguageName()));
            o.addProperty("autoGenerated", s.isAutoGenerated());
            arr.add(o);
        }
        return arr;
    }

    /**
     * 把 cookie 文件转成请求头格式。
     *
     * <p>视频工具箱的 data/guest_cookies.txt 是 yt-dlp 风格的 **Netscape** 文件
     * （7 个 tab 分隔字段：domain/flag/path/secure/expiry/name/value），
     * 直接去掉换行拼出来根本不是合法 Cookie 头，必须逐行取 name=value。
     * 若文件本身已是 "a=b; c=d" 的头格式，则原样透传。
     */
    private static String loadCookieFile(String path) throws IOException {
        String raw = new String(Files.readAllBytes(Paths.get(path)), StandardCharsets.UTF_8);
        StringBuilder sb = new StringBuilder();
        for (String line : raw.split("\r?\n")) {
            String l = line.trim();
            if (l.isEmpty()) {
                continue;
            }
            if (l.startsWith("#HttpOnly_")) {
                l = l.substring("#HttpOnly_".length()).trim();
            } else if (l.startsWith("#")) {
                continue;
            }
            String[] f = l.split("\t");
            String pair;
            if (f.length >= 7) {
                String name = f[5].trim();
                String value = f[6].trim();
                if (name.isEmpty()) {
                    continue;
                }
                pair = name + "=" + value;
            } else if (l.contains("=") && !l.startsWith("#")) {
                pair = l;
            } else {
                continue;
            }
            if (sb.length() > 0) {
                sb.append("; ");
            }
            sb.append(pair);
        }
        return sb.toString();
    }

    private static String nullToEmpty(String s) {
        return s == null ? "" : s;
    }

    private static String next(String[] args, int i) {
        return i < args.length ? args[i] : "";
    }
}
