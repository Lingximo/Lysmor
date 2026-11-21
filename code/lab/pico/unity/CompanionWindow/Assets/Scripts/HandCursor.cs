using UnityEngine;
using UnityEngine.UI;

namespace Companion
{
    /// <summary>官方手部射线没显示时，补一个始终跟随指向的圆环；捏合时放大/变亮。</summary>
    public class HandCursor : MonoBehaviour
    {
        public HandFocus hand;
        public Camera cam;

        Transform ring;
        Transform officialRay;
        Material mat;
        Color baseColor = new Color(0.25f, 0.9f, 1f, 0.95f);

        void Start()
        {
            if (cam == null) cam = Camera.main;
            var handRoot = GameObject.Find("OfficialHandRight");
            if (handRoot != null) officialRay = handRoot.transform.Find("RayPose");
            var go = new GameObject("HandRing");
            ring = go.transform;
            var mf = go.AddComponent<MeshFilter>();
            var mr = go.AddComponent<MeshRenderer>();
            mf.sharedMesh = BuildQuad();
            // Sprites/Default 是 Cull Off，圆环无论朝向都能看见
            var shader = Shader.Find("Sprites/Default");
            if (shader == null) shader = Shader.Find("Unlit/Transparent");
            mat = new Material(shader);
            mat.mainTexture = BuildRingTexture(128, 10);
            mat.color = baseColor;
            mr.material = mat;
            mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            mr.receiveShadows = false;
        }

        Mesh BuildQuad()
        {
            var m = new Mesh();
            m.vertices = new[] {
                new Vector3(-0.5f,-0.5f,0), new Vector3(0.5f,-0.5f,0),
                new Vector3(-0.5f,0.5f,0), new Vector3(0.5f,0.5f,0)
            };
            m.uv = new[] { new Vector2(0,0), new Vector2(1,0), new Vector2(0,1), new Vector2(1,1) };
            m.triangles = new[] { 0,2,1, 2,3,1 };
            m.RecalculateNormals();
            return m;
        }

        Texture2D BuildRingTexture(int size, int thickness)
        {
            var t = new Texture2D(size, size, TextureFormat.RGBA32, false);
            var px = new Color[size * size];
            float c = (size - 1) / 2f;
            float outer = size * 0.46f;
            float inner = outer - thickness;
            for (int y = 0; y < size; y++)
                for (int x = 0; x < size; x++)
                {
                    float d = Mathf.Sqrt((x - c) * (x - c) + (y - c) * (y - c));
                    float a = d <= outer && d >= inner ? 1f : 0f;
                    if (d < 2.5f) a = 1f;
                    px[y * size + x] = new Color(1, 1, 1, a);
                }
            t.SetPixels(px);
            t.Apply();
            t.wrapMode = TextureWrapMode.Clamp;
            return t;
        }

        void Update()
        {
            if (ring == null) return;
            bool show = hand != null && hand.HasHand;
            ring.gameObject.SetActive(show);
            if (!show) return;

            ring.position = hand.RayWorld;
            if (cam != null)
                ring.rotation = Quaternion.LookRotation(ring.position - cam.transform.position, Vector3.up);
            float s = hand.Pinching ? 0.070f : 0.045f;
            ring.localScale = new Vector3(s, s, s);
            if (mat != null)
                mat.color = hand.Pinching ? new Color(0.9f, 1f, 1f, 1f) : baseColor;
        }
    }
}
