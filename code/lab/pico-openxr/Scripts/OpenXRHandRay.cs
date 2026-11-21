using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.Hands;

namespace Companion
{
    /// <summary>OpenXR 手部射线：不渲染手，只从食指指尖画一条细线；捏合时变粗。</summary>
    public class OpenXRHandRay : MonoBehaviour
    {
        public float length = 1.6f;
        public float width = 0.004f;
        public float pinchDistance = 0.025f;

        XRHandSubsystem subsystem;
        LineRenderer line;
        Material mat;
        Transform tipMarker;
        float nextLog;
        bool lastPinch;

        void Start()
        {
            var go = new GameObject("OpenXRHandRay");
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

            var marker = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            marker.name = "HandRayTipMarker";
            marker.transform.SetParent(transform, false);
            marker.transform.localScale = Vector3.one * 0.012f;
            var collider = marker.GetComponent<Collider>();
            if (collider != null) Destroy(collider);
            var mr = marker.GetComponent<MeshRenderer>();
            if (mr != null) mr.material = mat;
            tipMarker = marker.transform;
            tipMarker.gameObject.SetActive(false);
        }

        void Update()
        {
            if (subsystem == null)
            {
                var list = new List<XRHandSubsystem>();
                SubsystemManager.GetSubsystems(list);
                if (list.Count > 0) subsystem = list[0];
            }
            if (subsystem == null || line == null) return;

            var hand = subsystem.rightHand;
            Pose tip = default;
            Pose thumb = default;
            bool hasTip = hand.GetJoint(XRHandJointID.IndexTip).TryGetPose(out tip);
            bool hasThumb = hand.GetJoint(XRHandJointID.ThumbTip).TryGetPose(out thumb);
            bool show = hand.isTracked && hasTip && hasThumb;
            line.enabled = show;
            if (tipMarker != null) tipMarker.gameObject.SetActive(show);
            if (!show) return;

            // 用“食指指尖 - 食指远端/近端”求真实指向；比 tip.rotation 稳，
            // 也比直接用 Pose.forward 更贴近手指实际方向。
            Vector3 dir = tip.rotation * Vector3.forward;
            Pose distal = default;
            Pose proximal = default;
            if (hand.GetJoint(XRHandJointID.IndexDistal).TryGetPose(out distal))
            {
                var d = tip.position - distal.position;
                if (d.sqrMagnitude > 1e-6f) dir = d.normalized;
            }
            else if (hand.GetJoint(XRHandJointID.IndexProximal).TryGetPose(out proximal))
            {
                var d = tip.position - proximal.position;
                if (d.sqrMagnitude > 1e-6f) dir = d.normalized;
            }

            if (tipMarker != null) tipMarker.position = tip.position;
            line.SetPosition(0, tip.position);
            line.SetPosition(1, tip.position + dir * length);

            bool pinch = Vector3.Distance(tip.position, thumb.position) < pinchDistance;
            float w = pinch ? width * 2.2f : width;
            line.startWidth = w;
            line.endWidth = w * 0.35f;
            if (mat != null)
                mat.color = pinch ? new Color(1f, 1f, 1f, 0.95f) : new Color(0.55f, 0.95f, 1f, 0.85f);

            if (Time.time > nextLog)
            {
                nextLog = Time.time + 1f;
                Debug.Log($"OpenXRHandRay tip={tip.position} dir={dir} pinch={pinch}");
            }
        }
    }
}
