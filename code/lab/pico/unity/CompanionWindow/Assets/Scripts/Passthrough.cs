using UnityEngine;
using Unity.XR.PXR;

namespace Companion
{
    /// <summary>
    /// 开彩色透视：让她和窗口浮在现实世界里，而不是黑底。
    /// </summary>
    public class Passthrough : MonoBehaviour
    {
        void Start()
        {
            PXR_Manager.EnableVideoSeeThrough = true;
            var cam = Camera.main;
            if (cam != null)
            {
                cam.clearFlags = CameraClearFlags.SolidColor;
                cam.backgroundColor = new Color(0f, 0f, 0f, 0f);
            }
        }
    }
}
