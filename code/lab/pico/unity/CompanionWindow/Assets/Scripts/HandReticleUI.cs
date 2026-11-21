using UnityEngine;
using UnityEngine.UI;

namespace Companion
{
    /// <summary>屏幕空间准星：不依赖手的 3D 世界坐标，UV 来自官方目标射线。</summary>
    public class HandReticleUI : MonoBehaviour
    {
        public HandFocus hand;
        public float size = 64f;

        Canvas canvas;
        RawImage image;
        RectTransform rt;
        Texture2D tex;

        void Start()
        {
            var go = new GameObject("HandReticleCanvas");
            go.transform.SetParent(transform, false);
            go.transform.localPosition = new Vector3(0f, 0f, 1.0f);
            go.transform.localRotation = Quaternion.identity;
            go.transform.localScale = Vector3.one * 0.00055f;
            canvas = go.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            var crt = go.GetComponent<RectTransform>();
            crt.sizeDelta = new Vector2(1008, 921);
            go.AddComponent<CanvasScaler>();

            var imgGo = new GameObject("Reticle");
            imgGo.transform.SetParent(go.transform, false);
            image = imgGo.AddComponent<RawImage>();
            rt = imgGo.GetComponent<RectTransform>();
            rt.sizeDelta = new Vector2(size, size);
            tex = BuildRing(128);
            image.texture = tex;
            image.color = new Color(0.25f, 0.9f, 1f, 0.95f);
            canvas.enabled = false;
        }

        Texture2D BuildRing(int n)
        {
            var t = new Texture2D(n, n, TextureFormat.RGBA32, false);
            var px = new Color[n * n];
            float c = (n - 1) / 2f, outer = n * 0.45f, inner = outer - 8f;
            for (int y = 0; y < n; y++)
                for (int x = 0; x < n; x++)
                {
                    float d = Mathf.Sqrt((x - c) * (x - c) + (y - c) * (y - c));
                    float a = (d <= outer && d >= inner) ? 1f : 0f;
                    if (d < 2.5f) a = 1f;
                    px[y * n + x] = new Color(1, 1, 1, a);
                }
            t.SetPixels(px);
            t.Apply();
            return t;
        }

        void Update()
        {
            bool show = hand != null && hand.HasHand;
            if (canvas != null) canvas.enabled = show;
            if (!show || rt == null) return;

            var uv = hand.PointerUV;
            rt.anchoredPosition = new Vector2((uv.x - 0.5f) * 1008f, (uv.y - 0.5f) * 921f);
            float s = hand.Pinching ? 1.5f : 1f;
            rt.localScale = Vector3.one * s;
            image.color = hand.Pinching ? Color.white : new Color(0.25f, 0.9f, 1f, 0.95f);
        }
    }
}
