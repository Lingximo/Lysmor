using UnityEngine;
using Unity.XR.PXR;

namespace Companion
{
    /// <summary>调试用：在官方右手食指关节位置画一个圆环，用来判断官方手位置是否正确。</summary>
    public class HandDebugRing : MonoBehaviour
    {
        public float radius = 0.035f;
        public int segments = 40;

        Transform tip;
        LineRenderer line;
        Material mat;

        void Start()
        {
            var hand = FindObjectOfType<PXR_Hand>(true);
            if (hand != null) tip = FindDeep(hand.transform, "right_index_distal");
            Debug.Log("HandDebugRing tip=" + (tip != null ? tip.name : "none"));

            var go = new GameObject("HandDebugRingLine");
            go.transform.SetParent(transform, false);
            line = go.AddComponent<LineRenderer>();
            line.useWorldSpace = false;
            line.loop = true;
            line.positionCount = segments;
            line.startWidth = 0.006f;
            line.endWidth = 0.006f;
            var shader = Shader.Find("Sprites/Default");
            if (shader == null) shader = Shader.Find("Unlit/Color");
            mat = new Material(shader);
            mat.color = new Color(1f, 0.35f, 0.1f, 0.95f);
            line.material = mat;
            line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            line.receiveShadows = false;
            line.enabled = false;
        }

        Transform FindDeep(Transform root, string n)
        {
            foreach (var t in root.GetComponentsInChildren<Transform>(true))
                if (t.name == n) return t;
            return null;
        }

        void Update()
        {
            if (line == null) return;
            bool show = tip != null && tip.gameObject.activeInHierarchy;
            line.enabled = show;
            if (!show) return;

            var cam = Camera.main;
            line.transform.position = tip.position;
            if (cam != null)
                line.transform.rotation = Quaternion.LookRotation(tip.position - cam.transform.position, Vector3.up);

            for (int i = 0; i < segments; i++)
            {
                float a = i * Mathf.PI * 2f / segments;
                line.SetPosition(i, new Vector3(Mathf.Cos(a) * radius, Mathf.Sin(a) * radius, 0f));
            }
        }
    }
}
