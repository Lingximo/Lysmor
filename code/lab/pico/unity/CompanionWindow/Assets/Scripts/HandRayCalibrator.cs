using UnityEngine;
using UnityEngine.XR;

namespace Companion
{
    /// <summary>让用户戴着头显直接校准手部射线位置，不再靠代码猜偏移。
    /// 右扳机按住：右摇杆调左右/上下，左摇杆上下调前后；松开保存。
    /// 右 A 键：恢复默认。</summary>
    public class HandRayCalibrator : MonoBehaviour
    {
        public PXRHandRay ray;
        public float speed = 0.35f;

        InputDevice right;
        InputDevice left;
        bool adjusting;
        bool moved;
        float nextHint;

        void Start()
        {
            if (ray == null) ray = FindObjectOfType<PXRHandRay>();
            Debug.Log("HandRayCalibrator: 右扳机按住调位置，右摇杆左右/上下，左摇杆上下前后，松开保存，A 重置");
        }

        void Update()
        {
            if (ray == null) return;

            if (!right.isValid) right = InputDevices.GetDeviceAtXRNode(XRNode.RightHand);
            if (!left.isValid) left = InputDevices.GetDeviceAtXRNode(XRNode.LeftHand);

            bool hold = false;
            right.TryGetFeatureValue(CommonUsages.triggerButton, out hold);

            if (hold)
            {
                adjusting = true;
                Vector2 r = Vector2.zero, l = Vector2.zero;
                right.TryGetFeatureValue(CommonUsages.primary2DAxis, out r);
                left.TryGetFeatureValue(CommonUsages.primary2DAxis, out l);

                var c = ray.calibration;
                c.x += r.x * speed * Time.deltaTime;
                c.y += r.y * speed * Time.deltaTime;
                c.z += l.y * speed * Time.deltaTime;
                ray.calibration = c;

                if (Mathf.Abs(r.x) + Mathf.Abs(r.y) + Mathf.Abs(l.y) > 0.05f)
                {
                    moved = true;
                    if (Time.time > nextHint)
                    {
                        nextHint = Time.time + 0.5f;
                        Debug.Log($"HandRayCalibrator: {c}");
                    }
                }
            }
            else
            {
                if (adjusting && moved)
                {
                    ray.SaveCalibration();
                    Debug.Log("HandRayCalibrator: saved " + ray.calibration);
                }
                adjusting = false;
                moved = false;
            }

            bool reset = false;
            right.TryGetFeatureValue(CommonUsages.primaryButton, out reset);
            if (reset)
            {
                ray.ResetCalibration();
                Debug.Log("HandRayCalibrator: reset");
            }
        }
    }
}
