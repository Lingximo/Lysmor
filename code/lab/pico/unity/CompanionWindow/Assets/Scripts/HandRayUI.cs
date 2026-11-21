using UnityEngine;
using UnityEngine.UI;

namespace Companion
{
    /// <summary>屏幕射线：从画面下方中央指向食指方向，末端就是放大中心。</summary>
    public class HandRayUI : MonoBehaviour
    {
        public HandFocus hand;
        public float width = 2.5f;

        Canvas canvas;
        RectTransform line;
        Image lineImg;
        RectTransform dot;
        Image dotImg;

        void Start()
        {
            var go = new GameObject("HandRayCanvas");
            go.transform.SetParent(transform, false);
            go.transform.localPosition = new Vector3(0, 0, 1.0f);
            go.transform.localRotation = Quaternion.identity;
            go.transform.localScale = Vector3.one * 0.00055f;
            canvas = go.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            go.GetComponent<RectTransform>().sizeDelta = new Vector2(1008, 921);
            go.AddComponent<CanvasScaler>();

            var lgo = new GameObject("Ray");
            lgo.transform.SetParent(go.transform, false);
            lineImg = lgo.AddComponent<Image>();
            lineImg.color = new Color(0.25f, 0.9f, 1f, 0.55f);
            lineImg.raycastTarget = false;
            line = lgo.GetComponent<RectTransform>();
            line.sizeDelta = new Vector2(10, width);

            var dgo = new GameObject("Tip");
            dgo.transform.SetParent(go.transform, false);
            dotImg = dgo.AddComponent<Image>();
            dotImg.color = new Color(0.35f, 0.95f, 1f, 0.95f);
            dotImg.raycastTarget = false;
            dot = dgo.GetComponent<RectTransform>();
            dot.sizeDelta = new Vector2(10, 10);

            canvas.enabled = false;
        }

        void Update()
        {
            bool show = hand != null && hand.HasHand;
            if (canvas != null) canvas.enabled = show;
            if (!show) return;

            var uv = hand.PointerUV;
            Vector2 end = new Vector2((uv.x - 0.5f) * 1008f, (uv.y - 0.5f) * 921f);
            Vector2 start = new Vector2(0f, -300f);
            Vector2 d = end - start;
            float len = d.magnitude;
            if (len < 1f) return;

            line.anchoredPosition = (start + end) * 0.5f;
            line.sizeDelta = new Vector2(len, hand.Pinching ? width * 2f : width);
            line.localRotation = Quaternion.Euler(0, 0, Mathf.Atan2(d.y, d.x) * Mathf.Rad2Deg);

            dot.anchoredPosition = end;
            float s = hand.Pinching ? 18f : 10f;
            dot.sizeDelta = new Vector2(s, s);
            dotImg.color = hand.Pinching ? Color.white : new Color(0.35f, 0.95f, 1f, 0.95f);

            // 轻微呼吸，避免死板
            lineImg.color = new Color(0.25f, 0.9f, 1f, 0.45f + 0.12f * Mathf.Sin(Time.time * 6f));
        }
    }
}
