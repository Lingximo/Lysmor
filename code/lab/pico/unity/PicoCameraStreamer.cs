// TA · Pico 透视相机推流（Unity + PICO SDK 3.4.0）
//
// 作用：把 Pico 4 Ultra 的双路 RGB 相机帧，压成 JPEG，POST 到电脑的 8804。
// 依赖：PICO Unity Integration SDK（PXR_CameraImage）
// 用法：挂在一个空 GameObject 上，Inspector 里填电脑 IP。
//
// 权限：AndroidManifest 需要有
//   <uses-permission android:name="android.permission.CAMERA" />
//   <uses-permission android:name="com.picovr.permission.SPATIAL_DATA" />
// 首次运行会弹权限，必须都允许。

using System;
using System.Collections;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.Networking;
using Unity.XR.PXR;
#if UNITY_ANDROID && !UNITY_EDITOR
using UnityEngine.Android;
#endif

public class PicoCameraStreamer : MonoBehaviour
{
    [Header("电脑地址")]
    [SerializeField] string pcHost = "192.168.1.2";
    [SerializeField] int pcPort = 8804;

    [Header("采集")]
    [SerializeField] int targetWidth = 640;
    [SerializeField] int targetHeight = 480;
    [SerializeField] int targetFps = 10;
    [SerializeField] int jpegQuality = 70;
    [SerializeField] bool sendLeftEye = true;
    [SerializeField] bool sendRightEye = false;

    [Header("状态")]
    [SerializeField] bool streaming = false;
    [SerializeField] int framesSent = 0;
    [SerializeField] string lastError = "";

    readonly List<XrCameraIdPICO> _active = new List<XrCameraIdPICO>();
    readonly Dictionary<XrCameraIdPICO, long> _lastTs = new Dictionary<XrCameraIdPICO, long>();
    readonly Dictionary<XrCameraIdPICO, Texture2D> _tex = new Dictionary<XrCameraIdPICO, Texture2D>();

    float _nextSend;
    bool _busy;

#if UNITY_ANDROID && !UNITY_EDITOR
    bool _permOk;
    const string SpatialPerm = "com.picovr.permission.SPATIAL_DATA";
#endif

    void Start()
    {
#if UNITY_ANDROID && !UNITY_EDITOR
        StartCoroutine(StartWithPermissions());
#else
        Debug.LogWarning("[PicoCam] 编辑器里没有 PXR_CameraImage，请在真机运行");
#endif
    }

#if UNITY_ANDROID && !UNITY_EDITOR
    IEnumerator StartWithPermissions()
    {
        var need = new List<string>();
        if (!Permission.HasUserAuthorizedPermission(Permission.Camera)) need.Add(Permission.Camera);
        if (!Permission.HasUserAuthorizedPermission(SpatialPerm)) need.Add(SpatialPerm);
        if (need.Count > 0)
        {
            var settled = false;
            var cb = new PermissionCallbacks();
            cb.PermissionGranted += _ => settled = true;
            cb.PermissionDenied += _ => settled = true;
            cb.PermissionDeniedAndDontAskAgain += _ => settled = true;
            Permission.RequestUserPermissions(need.ToArray(), cb);
            float t = 0;
            while (!settled && t < 120) { t += Time.unscaledDeltaTime; yield return null; }
        }
        _permOk = Permission.HasUserAuthorizedPermission(Permission.Camera)
                  && Permission.HasUserAuthorizedPermission(SpatialPerm);
        if (!_permOk)
        {
            lastError = "相机/空间权限被拒";
            Debug.LogError("[PicoCam] " + lastError);
            yield break;
        }
        yield return StartCoroutine(InitCameras());
    }
#endif

    IEnumerator InitCameras()
    {
        var ret = PXR_CameraImage.GetAvailableCameras(out var ids);
        if (ret != PxrResult.SUCCESS || ids == null || ids.Length == 0)
        {
            lastError = "GetAvailableCameras failed: " + ret;
            Debug.LogError("[PicoCam] " + lastError);
            yield break;
        }
        Debug.Log("[PicoCam] cameras=" + ids.Length);

        var wanted = new List<XrCameraIdPICO>();
        if (sendLeftEye) wanted.Add(XrCameraIdPICO.XR_CAMERA_ID_RGB_LEFT_PICO);
        if (sendRightEye) wanted.Add(XrCameraIdPICO.XR_CAMERA_ID_RGB_RIGHT_PICO);

        foreach (var camId in wanted)
        {
            if (Array.IndexOf(ids, camId) < 0) continue;

            var task = PXR_CameraImage.CreateCameraDeviceAsync(camId);
            while (!task.IsCompleted) yield return null;
            if (task.Result != PxrResult.SUCCESS) { Debug.LogWarning("[PicoCam] create device " + camId + " " + task.Result); continue; }

            int w = targetWidth, h = targetHeight;
            if (PXR_CameraImage.GetCameraImageResolutionCapability(camId, out var caps) == PxrResult.SUCCESS && caps != null && caps.Length > 0)
            {
                var best = caps[0];
                int bestD = int.MaxValue;
                foreach (var c in caps)
                {
                    int d = Math.Abs(c.width - targetWidth) + Math.Abs(c.height - targetHeight);
                    if (d < bestD) { bestD = d; best = c; }
                }
                w = best.width; h = best.height;
            }

            var sessTask = PXR_CameraImage.CreateCameraCaptureSessionAsync(
                camId, w, h,
                XrCameraImageFpsPICO.XR_CAMERA_IMAGE_FPS_30_PICO,
                XrCameraImageFormatPICO.XR_CAMERA_IMAGE_FORMAT_RGBA_8888_PICO,
                XrCameraDataTransferTypePICO.XR_CAMERA_DATA_TRANSFER_TYPE_RAW_BUFFER_PICO,
                XrCameraModelPICO.XR_CAMERA_MODEL_PINHOLE_PICO);
            while (!sessTask.IsCompleted) yield return null;
            if (sessTask.Result != PxrResult.SUCCESS) { Debug.LogWarning("[PicoCam] session " + camId + " " + sessTask.Result); continue; }

            if (PXR_CameraImage.BeginCameraCapture(camId) != PxrResult.SUCCESS)
            {
                Debug.LogWarning("[PicoCam] begin capture failed " + camId);
                continue;
            }

            _active.Add(camId);
            _lastTs[camId] = 0;
            _tex[camId] = new Texture2D(w, h, TextureFormat.RGBA32, false);
            Debug.Log("[PicoCam] streaming " + camId + " " + w + "x" + h);
        }

        streaming = _active.Count > 0;
        if (!streaming) lastError = "没有可用相机";
    }

    void Update()
    {
        if (!streaming || _busy) return;
        if (Time.unscaledTime < _nextSend) return;
        _nextSend = Time.unscaledTime + 1f / Mathf.Max(1, targetFps);

        foreach (var camId in _active)
        {
            if (PXR_CameraImage.AcquireCameraImage(camId, _lastTs[camId], out var imageId, out var captureTime) != PxrResult.SUCCESS)
                continue;

            try
            {
                if (PXR_CameraImage.GetCameraImageData(camId, imageId, out var raw) != PxrResult.SUCCESS ||
                    raw.buffer == IntPtr.Zero || raw.bufferSize == 0)
                    continue;

                var bytes = CopyTightRgba(ref raw);
                if (!_tex.TryGetValue(camId, out var tex) || tex.width != raw.width || tex.height != raw.height)
                {
                    tex = new Texture2D((int)raw.width, (int)raw.height, TextureFormat.RGBA32, false);
                    _tex[camId] = tex;
                }
                tex.LoadRawTextureData(bytes);
                tex.Apply(false);

                var jpg = tex.EncodeToJPG(jpegQuality);
                StartCoroutine(PostFrame(jpg));
                _lastTs[camId] = captureTime;
            }
            finally
            {
                PXR_CameraImage.ReleaseCameraImage(camId, imageId);
            }
            break;   // 一帧只发一只眼
        }
    }

    static byte[] CopyTightRgba(ref XrCameraImageDataRawBuffer raw)
    {
        int w = (int)raw.width, h = (int)raw.height, bpp = (int)raw.bytesPerPixel, stride = (int)raw.stride;
        int rowTight = w * bpp;
        var dst = new byte[rowTight * h];
        for (int y = 0; y < h; y++)
        {
            var row = IntPtr.Add(raw.buffer, y * stride);
            Marshal.Copy(row, dst, y * rowTight, rowTight);
        }
        return dst;
    }

    IEnumerator PostFrame(byte[] jpg)
    {
        _busy = true;
        string url = "http://" + pcHost + ":" + pcPort + "/frame?describe=1";
        using (var req = new UnityWebRequest(url, "POST"))
        {
            req.uploadHandler = new UploadHandlerRaw(jpg);
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "image/jpeg");
            req.timeout = 10;
            yield return req.SendWebRequest();
            if (req.result == UnityWebRequest.Result.Success) framesSent++;
            else lastError = req.error;
        }
        _busy = false;
    }

    void OnDestroy()
    {
        foreach (var camId in _active)
        {
            try { PXR_CameraImage.EndCameraCapture(camId); } catch { }
            try { PXR_CameraImage.DestroyCameraCaptureSession(camId); } catch { }
            try { PXR_CameraImage.DestroyCameraDevice(camId); } catch { }
        }
        _active.Clear();
    }
}
