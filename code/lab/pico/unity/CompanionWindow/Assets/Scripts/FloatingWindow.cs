using UnityEngine;

namespace Companion
{
    /// <summary>
    /// 悬在眼前右侧的窗口：世界固定，转头能看；只有当头转得太远时才慢慢跟回来。
    /// </summary>
    public class FloatingWindow : MonoBehaviour
    {
        public Vector3 offset = new Vector3(0.32f, 0.00f, 1.00f);
        public float recenterAngle = 70f;
        public float followSpeed = 1.8f;

        Camera cam;
        bool placed;

        void Start()
        {
            cam = Camera.main;
            Place(true);
        }

        void LateUpdate()
        {
            if (cam == null) cam = Camera.main;
            if (cam == null) return;

            Vector3 toWindow = transform.position - cam.transform.position;
            float angle = Vector3.Angle(cam.transform.forward, toWindow.normalized);

            if (!placed || angle > recenterAngle)
            {
                Place(false);
            }

            // 始终正面朝向人
            Vector3 look = transform.position - cam.transform.position;
            if (look.sqrMagnitude > 0.001f)
            {
                transform.rotation = Quaternion.LookRotation(look.normalized, Vector3.up);
            }
        }

        void Place(bool instant)
        {
            if (cam == null) return;
            Vector3 target = cam.transform.position + cam.transform.rotation * offset;
            if (instant)
            {
                transform.position = target;
            }
            else
            {
                transform.position = Vector3.Lerp(transform.position, target,
                    Time.deltaTime * followSpeed * 10f);
            }
            placed = true;
        }
    }
}
