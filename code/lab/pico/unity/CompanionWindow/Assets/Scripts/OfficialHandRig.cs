using UnityEngine;

namespace Companion
{
    /// <summary>官方 HandRight 的放置：PXR 手部坐标在 tracking space，用相机高度和右手镜像做一次校准。</summary>
    public class OfficialHandRig : MonoBehaviour
    {
        public Camera cam;
        public float eyeHeight = 1.6f;

        void LateUpdate()
        {
            if (cam == null) cam = Camera.main;
            float y = cam != null && cam.transform.position.y > 0.2f ? cam.transform.position.y : eyeHeight;
            transform.position = new Vector3(0f, -y, 0f);
            // PXR 手部是 OpenXR 右手系（-Z 朝前、X 方向相反）
            // 用 180° 旋转转换，而不是负缩放，避免网格法线翻转
            transform.rotation = Quaternion.Euler(0f, 180f, 0f);
            transform.localScale = Vector3.one;
        }
    }
}
