using UnityEngine;

namespace Companion
{
    /// <summary>真正的 3D 射线：起点是食指关节，终点是指向方向上的世界点。</summary>
    public class HandRay3D : MonoBehaviour
    {
        public HandFocus hand;
        public Camera cam;
        public float length = 1.6f;
        public float width = 0.006f;

        LineRenderer line;
        Material mat;

        void Start()
        {
            if (cam == null) cam = Camera.main;
            var go = new GameObject("HandRay3D");
            go.transform.SetParent(transform, false);
            line = go.AddComponent<LineRenderer>();
            line.positionCount = 2;
            line.useWorldSpace = true;
            line.startWidth = width;
            line.endWidth = width * 0.5f;
            var shader = Shader.Find("Sprites/Default");
            if (shader == null) shader = Shader.Find("Unlit/Color");
            mat = new Material(shader);
            mat.color = new Color(0.25f, 0.9f, 1f, 0.75f);
            line.material = mat;
            line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            line.receiveShadows = false;
            line.enabled = false;
        }

        void Update()
        {
            if (line == null) return;
            bool show = hand != null && hand.HasHand;
            line.enabled = show;
            if (!show) return;

            var uv = hand.PointerUV;
            Vector3 start = cam != null
                ? cam.ViewportToWorldPoint(new Vector3(uv.x, uv.y, 0.4f))
                : hand.HandOrigin;
            Vector3 end = cam != null
                ? cam.ViewportToWorldPoint(new Vector3(uv.x, uv.y, 1.5f))
                : start + hand.RayDirection * length;
            line.SetPosition(0, start);
            line.SetPosition(1, end);

            float w = hand.Pinching ? width * 2.2f : width;
            line.startWidth = w;
            line.endWidth = w * 0.4f;
            if (mat != null)
                mat.color = hand.Pinching ? new Color(0.9f, 1f, 1f, 0.95f) : new Color(0.25f, 0.9f, 1f, 0.7f);
        }
    }
}
