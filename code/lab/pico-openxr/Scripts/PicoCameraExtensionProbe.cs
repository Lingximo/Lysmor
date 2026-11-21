using System;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.XR.OpenXR.Features;

namespace Companion
{
    /// <summary>只探测官方 XR_PICO_camera_image 扩展有没有可调用的函数指针，不取帧。</summary>
#if UNITY_EDITOR
    [UnityEditor.XR.OpenXR.Features.OpenXRFeature(
        UiName = "Companion PICO Camera Probe",
        Company = "Companion",
        Desc = "Probe XR_PICO_camera_image entry points",
        FeatureId = "com.companion.openxr.cameraprobe",
        OpenxrExtensionStrings = "XR_PICO_camera_image XR_PICO_external_camera",
        BuildTargetGroups = new[] { UnityEditor.BuildTargetGroup.Android })]
#endif
    public class PicoCameraExtensionProbe : OpenXRFeature
    {
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        delegate int XrGetInstanceProcAddrDelegate(ulong instance, string name, out IntPtr function);

        static readonly string[] Names =
        {
            "xrGetPICOCameraImage",
            "xrGetCameraImagePICO",
            "xrEnumerateCameraImagePICO",
            "xrGetAvailableCamerasPICO",
            "xrCreateCameraDevicePICO",
            "xrCreateCameraCaptureSessionPICO",
            "xrBeginCameraCapturePICO",
            "xrEndCameraCapturePICO",
            "xrAcquireCameraImagePICO",
            "xrReleaseCameraImagePICO",
            "xrGetCameraImageDataPICO",
            "xrReleaseCameraImageDataPICO",
            "xrGetCameraIntrinsicsPICO",
            "xrGetCameraExtrinsicsPICO",
            "xrGetCameraPropertiesPICO",
            "xrEnumerateCamerasPICO",
            "xrGetCameraCountPICO",
            "xrGetCamerasPICO",
            "xrCreateCameraPICO",
            "xrDestroyCameraPICO",
            "xrOpenCameraPICO",
            "xrCreateCameraDevice2PICO",
            "xrCreateCameraSessionPICO",
            "xrCreateCaptureSessionPICO",
            "xrCreateCameraCaptureSession2PICO",
            "xrCreateCameraCapturePICO",
            "xrStartCameraCapturePICO",
            "xrGetCameraPICO",
            "xrGetCameraInfoPICO",
            "xrEnumerateCameraConfigurationsPICO",
            "xrGetCameraCapabilityPICO",
            "xrGetCameraCapabilityAvailablePICO",
            "xrGetCameraImageFpsCapabilityPICO",
            "xrGetCameraImageFormatCapabilityPICO",
            "xrGetCameraImageResolutionCapabilityPICO",
            "xrGetCameraDataTransferTypeCapabilityPICO",
            "xrGetCameraModelCapabilityPICO",
            "xrGetCameraFacingPICO",
            "xrGetCameraPositionPICO",
            "xrGetCameraTypePICO",
        };

        static bool logged;

        protected override bool OnInstanceCreate(ulong instance)
        {
            if (logged) return true;
            logged = true;
            try
            {
                var fn = (XrGetInstanceProcAddrDelegate)Marshal.GetDelegateForFunctionPointer(
                    xrGetInstanceProcAddr, typeof(XrGetInstanceProcAddrDelegate));
                foreach (var name in Names)
                {
                    IntPtr p = IntPtr.Zero;
                    int res = -1;
                    try { res = fn(instance, name, out p); }
                    catch (Exception e) { Debug.LogWarning("PicoCamProbe " + name + " call: " + e.Message); }
                    Debug.Log("PicoCamProbe " + name + " res=" + res + " ptr=" +
                              (p == IntPtr.Zero ? "NULL" : "0x" + p.ToInt64().ToString("X")));
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("PicoCamProbe init: " + e);
            }
            return true;
        }
    }
}
