using UnityEngine;
using Unity.XR.PXR;

namespace Companion
{
    /// <summary>
    /// 探针：启动时列一下 PICO 能用的相机，确认消费版能不能取帧。
    /// </summary>
    public class CameraProbe : MonoBehaviour
    {
        void Start()
        {
            try
            {
                var result = PXR_CameraImage.GetAvailableCameras(out XrCameraIdPICO[] ids);
                int n = ids == null ? 0 : ids.Length;
                Debug.Log($"CameraProbe result={result} count={n}");
                if (ids != null)
                {
                    foreach (var id in ids)
                    {
                        Debug.Log("CameraProbe id=" + id);
                    }
                }
            }
            catch (System.Exception e)
            {
                Debug.LogWarning("CameraProbe failed: " + e);
            }
        }
    }
}
