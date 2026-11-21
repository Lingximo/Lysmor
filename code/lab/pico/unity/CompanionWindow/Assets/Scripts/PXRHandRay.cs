using UnityEngine;
using Unity.XR.PXR;

namespace Companion
{
    /// <summary>把新版 OpenXR 的“指尖小球 + 细射线”手感搬到老 PXR 版：
    /// 用 PXR 的 HandAimState 指向，不依赖官方手模型的骨骼朝向。</summary>
    public class PXRHandRay : MonoBehaviour
    {
        public float length = 1.6f;
        public float width = 0.004f;
        public float pinchDistance = 0.025f;
        public Vector3 calibration = new Vector3(0f, -1.8f, 0f);
        const string OffsetKey = "companion.handray.offset";

        HandAimState aim;
        PXR_Hand handRoot;
        LineRenderer line;
        Material mat;
        Transform marker;
        float nextLog;
        bool lastPinch;

        public void SaveCalibration()
        {
            PlayerPrefs.SetFloat(OffsetKey + ".x", calibration.x);
            PlayerPrefs.SetFloat(OffsetKey + ".y", calibration.y);
            PlayerPrefs.SetFloat(OffsetKey + ".z", calibration.z);
            PlayerPrefs.Save();
        }

        public void ResetCalibration()
        {
            calibration = new Vector3(0f, -1.8f, 0f);
            SaveCalibration();
        }

        void Start()
        {
            calibration = new Vector3(
                PlayerPrefs.GetFloat(OffsetKey + ".x", 0f),
                PlayerPrefs.GetFloat(OffsetKey + ".y", -1.8f),
                PlayerPrefs.GetFloat(OffsetKey + ".z", 0f));
            var go = new GameObject("PXRHandRay");
            go.transform.SetParent(transform, false);
            line = go.AddComponent<LineRenderer>();
            line.positionCount = 2;
            line.useWorldSpace = true;
            line.startWidth = width;
            line.endWidth = width * 0.35f;
            var shader = Shader.Find("Sprites/Default");
            if (shader == null) shader = Shader.Find("Unlit/Color");
            mat = new Material(shader);
            mat.color = new Color(0.55f, 0.95f, 1f, 0.85f);
            line.material = mat;
            line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            line.receiveShadows = false;
            line.enabled = false;

            var m = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            m.name = "PXRTipMarker";
            m.transform.SetParent(transform, false);
            m.transform.localScale = Vector3.one * 0.03f;
            var c = m.GetComponent<Collider>();
            if (c != null) Destroy(c);
            var mr = m.GetComponent<MeshRenderer>();
            if (mr != null) mr.material = mat;
            marker = m.transform;
            marker.gameObject.SetActive(false);

            // 关掉官方默认射线，只保留这一条；官方手模型是否保留不影响功能。
            handRoot = FindObjectOfType<PXR_Hand>(true);
            if (handRoot != null)
            {
                var defRay = handRoot.transform.Find("RayPose/DefaultRay");
                if (defRay != null) defRay.gameObject.SetActive(false);
            }
        }

        void Update()
        {
            bool ok = PXR_HandTracking.GetAimState(HandType.HandRight, ref aim);
            bool computed = ok && (aim.aimStatus & HandAimStatus.AimComputed) != 0;
            if (!computed)
            {
                if (line != null) line.enabled = false;
                if (marker != null) marker.gameObject.SetActive(false);
                return;
            }

            // PXR 的 aimRayPose 是手根节点下的局部坐标，不是世界坐标；
            // 直接当世界坐标用会飘到头顶/前上方。
            Vector3 localPos = aim.aimRayPose.Position.ToVector3();
            Quaternion localRot = aim.aimRayPose.Orientation.ToQuat();
            Vector3 pos = handRoot != null ? handRoot.transform.TransformPoint(localPos) : localPos;
            Quaternion rot = handRoot != null ? handRoot.transform.rotation * localRot : localRot;
            Vector3 dir = rot * Vector3.forward;

            // 整只手：射线起点使用掌心，不再依赖食指。
            if (handRoot != null && handRoot.handJoints != null)
            {
                int palmId = (int)HandJoint.JointPalm;
                if (palmId < handRoot.handJoints.Count && handRoot.handJoints[palmId] != null)
                    pos = handRoot.handJoints[palmId].position;
            }
            // 位置偏移由用户在头显里用控制器实时校准。
            pos += calibration;

            if (Camera.main != null && Camera.main.WorldToViewportPoint(pos + dir).z < 0f)
                dir = -dir;

            line.enabled = true;
            marker.gameObject.SetActive(true);
            marker.position = pos;
            line.SetPosition(0, pos);
            line.SetPosition(1, pos + dir.normalized * length);

            bool pinch = PXRHandGesture.TryGetFist(HandType.HandRight, out float fistAvg);
            float w = pinch ? width * 2.2f : width;
            line.startWidth = w;
            line.endWidth = w * 0.35f;
            if (mat != null)
                mat.color = pinch ? new Color(1f, 1f, 1f, 0.95f) : new Color(0.55f, 0.95f, 1f, 0.85f);

            if (pinch != lastPinch || Time.time > nextLog)
            {
                lastPinch = pinch;
                nextLog = Time.time + 1f;
                var cam = Camera.main;
                Debug.Log($"PXRHandRay pos={pos} dir={dir} fist={pinch} distance={fistAvg:F3} cam={(cam != null ? cam.transform.position.ToString() : "null")} rot={(cam != null ? cam.transform.eulerAngles.ToString() : "-")} vp={(cam != null ? cam.WorldToViewportPoint(pos).ToString() : "-")}");
            }
        }
    }
}
