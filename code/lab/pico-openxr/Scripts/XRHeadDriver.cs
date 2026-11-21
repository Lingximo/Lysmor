using UnityEngine;
using UnityEngine.XR;

namespace Companion
{
    /// <summary>用 XR Head 设备驱动相机，补上 OpenXR 工程缺失的头部跟踪。</summary>
    public class XRHeadDriver : MonoBehaviour
    {
        void Update()
        {
            var head = InputDevices.GetDeviceAtXRNode(XRNode.Head);
            if (!head.isValid) return;
            if (head.TryGetFeatureValue(CommonUsages.centerEyePosition, out Vector3 p))
                transform.localPosition = p;
            if (head.TryGetFeatureValue(CommonUsages.centerEyeRotation, out Quaternion r))
                transform.localRotation = r;
        }
    }
}
