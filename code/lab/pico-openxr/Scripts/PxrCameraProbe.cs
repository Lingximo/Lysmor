using System;
using System.Collections;
using System.Runtime.InteropServices;
using UnityEngine;

namespace Companion
{
    /// <summary>最小验证：先给 PXR 平台设置参数，再枚举相机；不需要 PXR 的 XR 加载器。</summary>
    public class PxrCameraProbe : MonoBehaviour
    {
        [StructLayout(LayoutKind.Sequential)]
        struct UserDefinedSettings
        {
            public ushort stereoRenderingMode;
            public ushort colorSpace;
            public ushort systemDisplayFrequency;
            public ushort useContentProtect;
            public ushort optimizeBufferDiscards;
            public ushort enableAppSpaceWarp;
            public ushort enableSubsampled;
            public ushort lateLatchingDebug;
            public ushort enableStageMode;
            public ushort enableSuperResolution;
            public ushort normalSharpening;
            public ushort qualitySharpening;
            public ushort fixedFoveatedSharpening;
            public ushort selfAdaptiveSharpening;
            public ushort enableETFR;
            public ushort foveationLevel;
            public ushort spatialMeshLod;
            public ushort enableEyeTracking;
            public ushort dynamicFoveation;
        }

        [DllImport("PxrPlatform", CallingConvention = CallingConvention.Cdecl)]
        static extern void Pxr_SetUserDefinedSettings(UserDefinedSettings settings);

        [DllImport("PxrPlatform", CallingConvention = CallingConvention.Cdecl)]
        static extern int Pxr_GetAvailableCameras(ref uint count, ref IntPtr cameras);

        IEnumerator Start()
        {
            yield return new WaitForSeconds(2f);
            uint count = 0;
            IntPtr ptr = IntPtr.Zero;
            try
            {
                var settings = new UserDefinedSettings
                {
                    stereoRenderingMode = 0,
                    colorSpace = 1,
                    systemDisplayFrequency = 0,
                    useContentProtect = 0,
                    optimizeBufferDiscards = 1,
                    enableAppSpaceWarp = 0,
                    enableSubsampled = 0,
                    lateLatchingDebug = 0,
                    enableStageMode = 0,
                    enableSuperResolution = 0,
                    normalSharpening = 0,
                    qualitySharpening = 0,
                    fixedFoveatedSharpening = 0,
                    selfAdaptiveSharpening = 0,
                    enableETFR = 0,
                    foveationLevel = 0,
                    spatialMeshLod = 0,
                    enableEyeTracking = 0,
                    dynamicFoveation = 1,
                };
                Pxr_SetUserDefinedSettings(settings);
                Debug.Log("PxrCameraProbe: SetUserDefinedSettings done");

                int ret = Pxr_GetAvailableCameras(ref count, ref ptr);
                Debug.Log($"PxrCameraProbe: ret={ret} count={count} ptr={ptr}");
                if (ret == 0 && count > 0 && ptr != IntPtr.Zero)
                {
                    var ids = new long[count];
                    Marshal.Copy(ptr, ids, 0, (int)count);
                    Debug.Log("PxrCameraProbe: ids=" + string.Join(",", ids));
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("PxrCameraProbe: " + e);
            }
        }
    }
}
