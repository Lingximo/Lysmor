using System;
using System.Net.Http;
using System.Threading.Tasks;
using Unity.XR.PXR;
using UnityEngine;
using UnityEngine.Android;

namespace Companion
{
    /// <summary>
    /// 取 PICO 相机的一帧，发到电脑的视觉端点。
    /// 消费版可能没有相机权限，所以全部包在 try/catch 里，失败不影响窗口。
    /// </summary>
    public class CameraVision : MonoBehaviour
    {
        public string endpoint = "http://192.168.1.2:8003/api/pico_look";
        public int width = 640;
        public int height = 480;
        public float interval = 4f;
        public Texture2D PreviewTexture { get; private set; }
        public string LastVisionText { get; private set; } = "";
        public float PreviewAt { get; private set; }
        public float LastVisionAt { get; private set; }
        public bool HasFreshPreview(float maxAge = 30f) => PreviewTexture != null && PreviewAt > 0f && Time.time - PreviewAt <= maxAge;
        public bool HasFreshVision(float maxAge = 30f) => !string.IsNullOrEmpty(LastVisionText) && LastVisionAt > 0f && Time.time - LastVisionAt <= maxAge;
        public bool extraMirror = false;
        bool fastMode;
        bool savedPreview;
        bool hasFocus;
        float focusU = 0.5f, focusV = 0.5f, focusZoom = 2f;
        public void SetFocus(float u, float v) { focusU = Mathf.Clamp01(u); focusV = Mathf.Clamp01(v); }

        XrCameraIdPICO cameraId;
        bool ready;
        bool busy;
        bool warmup;
        bool restarting;
        int acquireFailures;
        long lastCaptureTime;
        float nextAt;
        float initRetryAt;
        static readonly HttpClient http = new HttpClient { Timeout = TimeSpan.FromSeconds(4) };

        void Start()
        {
            // 相机保持关闭，等用户握拳/捏合开窗后再初始化
            Debug.Log("CameraVision idle (will open on HUD)");
        }

        async Task InitCamera()
        {
            if (restarting) return;
            restarting = true;
            try
            {
                if (!Permission.HasUserAuthorizedPermission("android.permission.CAMERA"))
                {
                    Permission.RequestUserPermission("android.permission.CAMERA");
                    await Task.Delay(1500);
                }

                var res = PXR_CameraImage.GetAvailableCameras(out XrCameraIdPICO[] ids);
                Debug.Log($"CameraVision cameras={res} count={(ids == null ? 0 : ids.Length)}");
                if (ids == null || ids.Length == 0) return;
                cameraId = ids[0];

                var dev = await PXR_CameraImage.CreateCameraDeviceAsync(cameraId);
                Debug.Log("CameraVision device=" + dev);
                if (dev != PxrResult.SUCCESS) return;

                PxrResult ses = (PxrResult)(-1);
                var sizes = new[] { new[] { 1280, 720 }, new[] { 640, 480 }, new[] { 320, 240 } };
                foreach (var s in sizes)
                {
                    width = s[0];
                    height = s[1];
                    ses = await PXR_CameraImage.CreateCameraCaptureSessionAsync(
                        cameraId, width, height,
                        XrCameraImageFpsPICO.XR_CAMERA_IMAGE_FPS_30_PICO,
                        XrCameraImageFormatPICO.XR_CAMERA_IMAGE_FORMAT_RGBA_8888_PICO,
                        XrCameraDataTransferTypePICO.XR_CAMERA_DATA_TRANSFER_TYPE_RAW_BUFFER_PICO,
                        XrCameraModelPICO.XR_CAMERA_MODEL_PINHOLE_PICO);
                    Debug.Log($"CameraVision session {width}x{height} => {ses}");
                    if (ses == PxrResult.SUCCESS) break;
                }
                if (ses != PxrResult.SUCCESS) return;

                var begin = PXR_CameraImage.BeginCameraCapture(cameraId);
                Debug.Log("CameraVision begin=" + begin);
                ready = begin == PxrResult.SUCCESS;
                acquireFailures = 0;
                Debug.Log("CameraVision session ready=" + ready);
            }
            catch (Exception e)
            {
                Debug.LogWarning("CameraVision init: " + e);
            }
            finally
            {
                restarting = false;
            }
        }

        async void ReinitCamera()
        {
            if (restarting) return;
            restarting = true;
            try
            {
                ready = false;
                busy = false;
                warmup = false;
                if (PreviewTexture != null)
                {
                    Destroy(PreviewTexture);
                    PreviewTexture = null;
                }
                try
                {
                    PXR_CameraImage.DestroyCameraCaptureSession(cameraId);
                    PXR_CameraImage.DestroyCameraDevice(cameraId);
                }
                catch { }
                await Task.Delay(500);
            }
            finally
            {
                restarting = false;
            }
            if (!fastMode && !warmup) return;
            await InitCamera();
        }

        void ReleaseCamera()
        {
            try
            {
                if (ready)
                {
                    PXR_CameraImage.DestroyCameraCaptureSession(cameraId);
                    PXR_CameraImage.DestroyCameraDevice(cameraId);
                }
            }
            catch { }
            ready = false;
            busy = false;
            warmup = false;
            restarting = false;
        }

        void OnApplicationPause(bool paused)
        {
            if (paused)
            {
                // 后台/睡眠：彻底释放相机
                ReleaseCamera();
            }
            else if (fastMode)
            {
                // 只有窗口还开着才恢复相机
                warmup = true;
                nextAt = 0f;
                if (!ready) _ = InitCamera();
            }
        }

        public void SetFastMode(bool on)
        {
            fastMode = on;
            nextAt = 0;
            if (on)
            {
                warmup = true;
                initRetryAt = 0f;
                if (!ready && !restarting) _ = InitCamera();
                Debug.Log("CameraVision warmup requested");
            }
            else
            {
                // 关窗即释放，避免没握拳时相机还在采集
                ReleaseCamera();
            }
        }

        public void FocusAt(float u, float v, float zoomValue)
        {
            focusU = u;
            focusV = v;
            focusZoom = Mathf.Max(1f, zoomValue);
            hasFocus = true;
            nextAt = 0;
        }

        float dbgNext;
        float nextVisionPost;
        // 2026-11-16 省流：画面没变就不上传。带容错：头轻微晃动/呼吸不算"变了"。
        float[] lastSentThumb;
        Vector3 lastSentColor;
        bool hasLastColor;
        float lastPostAt = -999f;
        int postedFrames;
        int diffDbg;
        int skippedFrames;
        const int TW = 24;                 // 指纹 24×24
        const float SAME_THRESHOLD = 0.45f;   // 灰度差阈值（标准差归一化后，约 0.45σ）
        const float COLOR_THRESHOLD = 0.14f;  // 颜色差阈值（整体色偏要明显才算）
        const float IDLE_POST_SECONDS = 15f;
        const float MIN_POST_GAP = 6f;      // 相邻两次上传至少隔 6 秒
        const int CHANGE_CONFIRM = 2;       // 连续 2 次判"变了"才传（滤掉瞬时晃动）
        int changedStreak;
        bool wantFresh;   // 服务端说"看看"，下一帧立刻发
        bool probeFresh;  // 探询到服务端要新帧
        bool probeBusy;   // 上一发探询还没回来
        float nextProbe;
        float[] currentThumb;
        Vector3 currentColor;
        byte[] pendingVisionJpg;
        float pendingVisionAt;
        bool visionPosting;
        void Update()
        {
            if ((fastMode || warmup) && Time.time > dbgNext)
            {
                dbgNext = Time.time + 2f;
                Debug.Log($"CameraVision fast ready={ready} busy={busy} warmup={warmup} preview={(PreviewTexture != null)} next={nextAt:F1} now={Time.time:F1}");
            }
            if (!ready)
            {
                // 初始化失败/会话重建后，只要窗口还开着就继续重试
                if ((fastMode || warmup) && !restarting && Time.time >= initRetryAt)
                {
                    initRetryAt = Time.time + 2f;
                    Debug.Log("CameraVision retry init");
                    _ = InitCamera();
                }
                return;
            }
            if (fastMode && Time.time >= nextProbe)
            {
                nextProbe = Time.time + 1.5f;
                _ = ProbeWantFresh();
            }
            if (busy || Time.time < nextAt) return;
            nextAt = Time.time + (fastMode ? 0.1f : (warmup ? 0.5f : interval));
            _ = Grab();
        }

        async Task Grab()
        {
            busy = true;
            ulong imageId = 0;
            try
            {
                var acq = PXR_CameraImage.AcquireCameraImage(cameraId, lastCaptureTime,
                    out imageId, out long captureTime);
                if (acq != PxrResult.SUCCESS)
                {
                    acquireFailures++;
                    Debug.Log("CameraVision fast acquire=" + acq);
                    Debug.Log("CameraVision acquire=" + acq);
                    nextAt = Time.time + 0.5f;
                    if (acquireFailures >= 5)
                    {
                        acquireFailures = 0;
                        Debug.LogWarning("CameraVision acquire failed 5x, rebuilding session");
                        ReinitCamera();
                    }
                    return;
                }
                acquireFailures = 0;
                lastCaptureTime = captureTime;
                var get = PXR_CameraImage.GetCameraImageData(cameraId, imageId,
                    out XrCameraImageDataRawBuffer raw);
                if (get == PxrResult.SUCCESS && raw.buffer != IntPtr.Zero)
                {
                    int w = (int)raw.width, h = (int)raw.height;
                    int size = w * h * 4;
                    var bytes = new byte[size];
                    System.Runtime.InteropServices.Marshal.Copy(raw.buffer, bytes, 0, Math.Min(size, (int)raw.bufferSize));
                    var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
                    tex.LoadRawTextureData(bytes);
                    tex.Apply();

                    if (fastMode || warmup)
                    {
                        // CPU 裁切 + 水平镜像，彻底绕开 shader 的 Tiling 被剥离问题
                        int cw = Mathf.Max(32, w / 2);
                        int ch = Mathf.Max(32, cw * 9 / 16);
                        int x0 = Mathf.Clamp((int)(focusU * w) - cw / 2, 0, w - cw);
                        int y0 = Mathf.Clamp((int)(focusV * h) - ch / 2, 0, h - ch);
                        var crop = tex.GetPixels(x0, y0, cw, ch);
                        // 原始帧方向已经是正确的，不再翻转。
                        // PICO 彩色相机在室内偏暗；先按平均亮度自适应提亮，
                        // HUD 和识图用同一张已提亮图，避免“HUD 正常、模型说太黑”。
                        float lum = 0f;
                        for (int i = 0; i < crop.Length; i++)
                            lum += crop[i].r * 0.299f + crop[i].g * 0.587f + crop[i].b * 0.114f;
                        lum = crop.Length > 0 ? lum / crop.Length : 0f;
                        float gain = Mathf.Clamp(0.38f / Mathf.Max(lum, 0.03f), 1.0f, 3.0f);
                        for (int i = 0; i < crop.Length; i++)
                        {
                            var c = crop[i];
                            c.r = Mathf.Min(1f, c.r * gain);
                            c.g = Mathf.Min(1f, c.g * gain);
                            c.b = Mathf.Min(1f, c.b * gain);
                            crop[i] = c;
                        }

                        if (PreviewTexture == null || PreviewTexture.width != cw || PreviewTexture.height != ch)
                        {
                            if (PreviewTexture != null) Destroy(PreviewTexture);
                            PreviewTexture = new Texture2D(cw, ch, TextureFormat.RGBA32, false);
                            PreviewTexture.wrapMode = TextureWrapMode.Clamp;
                        }
                        PreviewTexture.SetPixels(crop);
                        PreviewTexture.Apply();
                        PreviewAt = Time.time;
                        warmup = false;
                        currentThumb = MakeThumb(crop, cw, ch, out currentColor);

                        if (!savedPreview)
                        {
                            savedPreview = true;
                            try
                            {
                                var path = System.IO.Path.Combine(Application.persistentDataPath, "preview.png");
                                System.IO.File.WriteAllBytes(path, PreviewTexture.EncodeToPNG());
                                Debug.Log($"CameraVision crop {cw}x{ch} from {x0},{y0} focus={focusU:F2},{focusV:F2}");
                            }
                            catch (System.Exception e) { Debug.LogWarning("preview save: " + e.Message); }
                        }
                    }

                    if (!hasFocus && fastMode && Time.time >= nextVisionPost)
                    {
                        // 2026-11-16 省流：画面几乎没变就不发；但最多 IDLE_POST_SECONDS 秒补一张，
                        // 保证 PC 那边永远有一张不太旧的图可以给"看看"用。
                        float idle = Time.time - lastPostAt;
                        bool force = idle >= IDLE_POST_SECONDS;
                        float diff = (lastSentThumb == null || currentThumb == null)
                                     ? 1f : ThumbDiffShift(lastSentThumb, currentThumb);
                        float cdiff = hasLastColor ? ColorDiff(lastSentColor, currentColor) : 1f;
                        bool changed = diff >= SAME_THRESHOLD || cdiff >= COLOR_THRESHOLD;
                        if (changed) changedStreak++;
                        else changedStreak = 0;
                        bool firstFrame = lastSentThumb == null;
                        bool gapOk = (Time.time - lastPostAt) >= MIN_POST_GAP;
                        bool confirmed = changedStreak >= CHANGE_CONFIRM;
                        bool doPost_force = wantFresh;
                        if (wantFresh) { wantFresh = false; }
                        bool forceProbe = probeFresh;
                        probeFresh = false;
                        bool doPost = force || firstFrame || doPost_force || forceProbe || (confirmed && gapOk);
                        if (diffDbg < 8)
                        {
                            diffDbg++;
                            Debug.Log($"[省流] 灰度差 {diff:F3}σ / 色差 {cdiff:F3} streak={changedStreak} → {(doPost ? "上传" : "跳过")}");
                        }
                        try
                        {
                            string p = System.IO.Path.Combine(Application.persistentDataPath, "vision_diff.log");
                            try
                            {
                                var fi = new System.IO.FileInfo(p);
                                if (fi.Exists && fi.Length > 256 * 1024) System.IO.File.Delete(p);
                            }
                            catch (System.Exception) { }
                            System.IO.File.AppendAllText(p,
                                string.Format("{0:F1},{1:F4},{2:F4},{3}\n", Time.time, diff, cdiff, doPost ? "post" : "skip"));
                        }
                        catch (System.Exception) { }
                        if (doPost)
                        {
                            nextVisionPost = Time.time + 3f;
                            lastPostAt = Time.time;
                            lastSentThumb = currentThumb;
                            lastSentColor = currentColor;
                            hasLastColor = true;
                            // 识图必须发已经裁切、提亮的同一张画面，不能发原始暗帧
                            var visionTex = PreviewTexture != null ? PreviewTexture : tex;
                            byte[] vj = visionTex.EncodeToJPG(74);
                            if (vj != null && vj.Length > 0) QueueVision(vj, EpochNow()); // 只保留最新帧
                            postedFrames++;
                            if (postedFrames == 1 || postedFrames % 20 == 0)
                                Debug.Log($"[省流] 已发 {postedFrames} 帧 / 跳过 {skippedFrames} 帧（画面没变）");
                        }
                        else
                        {
                            skippedFrames++;
                            nextVisionPost = Time.time + 2.5f;   // 只是检查，不上传
                        }
                    }

                    if (hasFocus)
                    {
                        hasFocus = false;
                        var crop = Crop(tex, focusU, focusV, focusZoom);
                        if (crop != null)
                        {
                            byte[] fj = crop.EncodeToJPG(85);
                            Destroy(crop);
                            await Post(fj, EpochNow());
                        }
                    }

                    if (!fastMode && !warmup) Destroy(tex);
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("CameraVision grab: " + e);
            }
            finally
            {
                if (imageId != 0) PXR_CameraImage.ReleaseCameraImage(cameraId, imageId);
                busy = false;
            }
        }


        Texture2D Crop(Texture2D src, float u, float v, float zoomValue)
        {
            int w = src.width, h = src.height;
            int cw = Mathf.Clamp(Mathf.RoundToInt(w / zoomValue), 32, w);
            int ch = Mathf.Clamp(Mathf.RoundToInt(h / zoomValue), 32, h);
            int x = Mathf.Clamp(Mathf.RoundToInt(u * w - cw / 2f), 0, w - cw);
            int y = Mathf.Clamp(Mathf.RoundToInt((1f - v) * h - ch / 2f), 0, h - ch);
            var outTex = new Texture2D(cw, ch, TextureFormat.RGB24, false);
            outTex.SetPixels(src.GetPixels(x, y, cw, ch));
            outTex.Apply();
            Debug.Log($"CameraFocus u={u:F2} v={v:F2} crop={x},{y},{cw}x{ch}");
            return outTex;
        }

        static float EpochNow() => (float)(System.DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0);

        /// <summary>24×24 灰度指纹（0..1，已去均值）+ 整幅平均色。
        /// 每格取平均抗噪；去均值让"自动提亮/整体亮度微变"不算变化。</summary>
        static float[] MakeThumb(Color[] px, int w, int h, out Vector3 meanColor)
        {
            meanColor = Vector3.zero;
            if (px == null || w <= 0 || h <= 0) return null;
            var thumb = new float[TW * TW];
            float total = 0f;
            for (int gy = 0; gy < TW; gy++)
            {
                int y0 = gy * h / TW;
                int y1 = Mathf.Max(y0 + 1, (gy + 1) * h / TW);
                for (int gx = 0; gx < TW; gx++)
                {
                    int x0 = gx * w / TW;
                    int x1 = Mathf.Max(x0 + 1, (gx + 1) * w / TW);
                    float sum = 0f;
                    int n = 0;
                    for (int y = y0; y < y1 && y < h; y++)
                    {
                        int row = y * w;
                        for (int x = x0; x < x1 && x < w; x++)
                        {
                            var c = px[row + x];
                            sum += c.r * 0.299f + c.g * 0.587f + c.b * 0.114f;
                            n++;
                        }
                    }
                    if (n <= 0) n = 1;
                    float v = sum / n;
                    thumb[gy * TW + gx] = v;
                    total += v;
                }
            }
            float mean = total / (TW * TW);
            float var = 0f;
            for (int i = 0; i < thumb.Length; i++)
            {
                float d = thumb[i] - mean;
                var += d * d;
            }
            var /= (TW * TW);
            float std = Mathf.Sqrt(Mathf.Max(var, 1e-6f));
            for (int i = 0; i < thumb.Length; i++) thumb[i] = (thumb[i] - mean) / std;

            float sr = 0f, sg = 0f, sb = 0f;
            int sn = 0;
            for (int y = 0; y < h; y += 8)
            {
                int row = y * w;
                for (int x = 0; x < w; x += 8)
                {
                    var c = px[row + x];
                    sr += c.r; sg += c.g; sb += c.b; sn++;
                }
            }
            sn = Mathf.Max(1, sn);
            meanColor = new Vector3(sr / sn, sg / sn, sb / sn);
            return thumb;
        }

        /// <summary>带容错的灰度差：允许 ±1 格平移（约 ±(宽/24) 像素），取最相似的一组。
        /// 这样头轻微晃动、呼吸、手抖都不算"画面变了"。</summary>
        static float ThumbDiffShift(float[] a, float[] b)
        {
            if (a == null || b == null || a.Length != b.Length) return 1f;
            float best = 1f;
            for (int dy = -1; dy <= 1; dy++)
            {
                for (int dx = -1; dx <= 1; dx++)
                {
                    float sum = 0f;
                    int n = 0;
                    for (int y = 1; y < TW - 1; y++)
                    {
                        int bRow = y + dy;
                        if (bRow < 0 || bRow >= TW) continue;
                        for (int x = 1; x < TW - 1; x++)
                        {
                            int bCol = x + dx;
                            if (bCol < 0 || bCol >= TW) continue;
                            sum += Mathf.Abs(a[y * TW + x] - b[bRow * TW + bCol]);
                            n++;
                        }
                    }
                    if (n > 0)
                    {
                        float d = sum / n;
                        if (d < best) best = d;
                    }
                }
            }
            return best;
        }

        static float ColorDiff(Vector3 a, Vector3 b)
        {
            return Mathf.Max(Mathf.Abs(a.x - b.x), Mathf.Max(Mathf.Abs(a.y - b.y), Mathf.Abs(a.z - b.z)));
        }

        async Task ProbeWantFresh()
        {
            if (probeBusy) return;
            probeBusy = true;
            try
            {
                string baseUrl = endpoint;
                int q = baseUrl.IndexOf("/api/pico_look");
                if (q < 0) return;
                string query = "";
                int qi = baseUrl.IndexOf('?');
                if (qi >= 0) query = baseUrl.Substring(qi);
                string probeUrl = baseUrl.Substring(0, q).TrimEnd('/') + "/api/pico_probe" + query;
                var resp = await http.GetAsync(probeUrl);
                if (resp == null || !resp.IsSuccessStatusCode) return;
                string text = await resp.Content.ReadAsStringAsync();
                if (text != null && text.Contains("true")) probeFresh = true;
            }
            catch (System.Exception) { }
            finally { probeBusy = false; }
        }

        void QueueVision(byte[] jpg, float frameAt)
        {
            pendingVisionJpg = jpg;
            pendingVisionAt = frameAt;
            if (!visionPosting) _ = DrainVision();
        }

        async Task DrainVision()
        {
            visionPosting = true;
            try
            {
                while (pendingVisionJpg != null)
                {
                    var jpg = pendingVisionJpg;
                    var at = pendingVisionAt;
                    pendingVisionJpg = null;
                    await Post(jpg, at);
                }
            }
            finally
            {
                visionPosting = false;
                if (pendingVisionJpg != null) _ = DrainVision();
            }
        }

        async Task Post(byte[] jpg, float frameAt)
        {
            // 识图调用保证：失败后短延迟重试一次，仍失败就留给下一帧
            for (int attempt = 0; attempt < 2; attempt++)
            {
                try
                {
                    using var content = new ByteArrayContent(jpg);
                    content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("image/jpeg");
                    content.Headers.TryAddWithoutValidation("X-Frame-Ts", frameAt.ToString("F3", System.Globalization.CultureInfo.InvariantCulture));
                    var resp = await http.PostAsync(endpoint, content);
                    string text = await resp.Content.ReadAsStringAsync();
                    Debug.Log("CameraVision vision=" + (text.Length > 160 ? text.Substring(0, 160) : text));
                    try
                    {
                        var vr = JsonUtility.FromJson<VisionReply>(text);
                        if (vr != null && vr.want_fresh) wantFresh = true;
                        if (vr != null && !vr.stale && !string.IsNullOrEmpty(vr.caption))
                        {
                            LastVisionText = vr.caption;
                            LastVisionAt = Time.time;
                        }
                    }
                    catch { }
                    return;
                }
                catch (Exception e)
                {
                    Debug.LogWarning("CameraVision post(" + (attempt + 1) + "): " + e.Message);
                    if (attempt == 0) await Task.Delay(800);
                }
            }
        }

        [System.Serializable]
        class VisionReply { public string caption; public bool stale; public bool want_fresh; }

        void OnDestroy()
        {
            try
            {
                if (ready)
                {
                    PXR_CameraImage.DestroyCameraCaptureSession(cameraId);
                    PXR_CameraImage.DestroyCameraDevice(cameraId);
                }
            }
            catch { }
        }
    }
}
