using UnityEngine;
using Unity.XR.PXR;

namespace Companion
{
    /// <summary>官方 HandAimState 射线；用 RayPose 的 Unity 变换校正方向。</summary>
    public class HandFocus : MonoBehaviour
    {
        public CameraMagnifier magnifier;
        public Vector2 PointerUV { get; private set; } = new Vector2(0.5f, 0.5f);
        public bool HasHand { get; private set; }
        public bool Pinching { get; private set; }
        public Vector3 RayWorld { get; private set; }
        public Vector3 RayDirection { get; private set; } = Vector3.forward;
        public Vector3 HandOrigin => indexTip != null && indexTip.gameObject.activeInHierarchy
            ? indexTip.position
            : (Camera.main != null ? Camera.main.transform.position + Camera.main.transform.rotation * new Vector3(0.2f, -0.3f, 0.3f) : RayWorld);

        HandAimState aim;
        float pinchSince = -1f;
        float cooldownUntil;
        bool fired;
        float nextLog;
        Transform officialRay;
        Transform indexTip;

        void Start()
        {
            var hand = FindObjectOfType<PXR_Hand>(true);
            if (hand != null)
            {
                officialRay = hand.transform.Find("RayPose");
                indexTip = FindDeep(hand.transform, "right_index_distal");
                var defRay = officialRay != null ? officialRay.Find("DefaultRay") : hand.transform.Find("DefaultRay");
                Debug.Log($"HandDebug ray={(officialRay != null)} rayActive={(officialRay != null && officialRay.gameObject.activeInHierarchy)} defRay={(defRay != null)} defActive={(defRay != null && defRay.gameObject.activeInHierarchy)}");
                if (defRay != null) {
                    defRay.gameObject.SetActive(true);
                    foreach (var rr in defRay.GetComponentsInChildren<Renderer>(true)) rr.enabled = true;
                    var rs = defRay.GetComponentsInChildren<Renderer>(true);
                    Debug.Log("HandDebug defRenderers=" + rs.Length + " enabled=" + (rs.Length > 0 ? rs[0].enabled.ToString() : "none"));
                }
            }
            Debug.Log("HandFocus officialRay=" + (officialRay != null ? officialRay.name : "none"));
        }

        Transform FindDeep(Transform root, string name)
        {
            foreach (var t in root.GetComponentsInChildren<Transform>(true))
                if (t.name == name) return t;
            return null;
        }

        void Update()
        {
            HasHand = false;
            Pinching = false;
            if (!PXR_HandTracking.GetAimState(HandType.HandRight, ref aim)) return;

            bool computed = (aim.aimStatus & HandAimStatus.AimComputed) != 0;
            bool rayValid = (aim.aimStatus & HandAimStatus.AimRayValid) != 0;
            if (!computed) { pinchSince = -1f; fired = false; return; }
            HasHand = true;

            Vector3 pos, fwd;
            if (indexTip != null && indexTip.gameObject.activeInHierarchy)
            {
                pos = indexTip.position;
                fwd = indexTip.forward;
            }
            else if (officialRay != null && officialRay.gameObject.activeInHierarchy)
            {
                pos = officialRay.position;
                fwd = officialRay.forward;
            }
            else
            {
                pos = aim.aimRayPose.Position.ToVector3();
                var rot = aim.aimRayPose.Orientation.ToQuat();
                fwd = rot * Vector3.forward;
                if (Camera.main != null && Camera.main.WorldToViewportPoint(pos + fwd).z < 0f)
                    fwd = -fwd; // OpenXR 坐标系方向反了
            }

            RayWorld = pos + fwd * 1.2f;
            RayDirection = fwd.normalized;
            var vp = Camera.main != null ? Camera.main.WorldToViewportPoint(RayWorld) : new Vector3(0.5f, 0.5f, 1f);
            PointerUV = new Vector2(Mathf.Clamp01(vp.x), Mathf.Clamp01(vp.y));

            bool pinching = PXRHandGesture.TryGetFist(HandType.HandRight, out float fistAvg);
            Pinching = pinching;

            if (pinching)
            {
                if (pinchSince < 0f) pinchSince = Time.time;
            }
            else
            {
                pinchSince = -1f;
                // 松开后 0.5 秒才允许下一次触发，避免同一捏合被算成两次
                if (fired && Time.time > cooldownUntil + 0.5f) fired = false;
            }

            if (!fired && pinchSince > 0f && Time.time - pinchSince > 0.25f && Time.time > cooldownUntil)
            {
                fired = true;
                cooldownUntil = Time.time + 1.2f;
                if (magnifier != null)
                {
                    magnifier.Toggle();
                    if (magnifier.Active && magnifier.vision != null)
                        magnifier.vision.FocusAt(PointerUV.x, PointerUV.y, magnifier.zoom);
                }
            }

            if (Time.time > nextLog)
            {
                nextLog = Time.time + 3f;
                Debug.Log($"HandFocus pos={pos} fwd={fwd} uv={PointerUV} fist={pinching} distance={fistAvg:F3} valid={rayValid} ray={officialRay != null}");
            }
        }
    }
}
