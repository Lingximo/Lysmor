using UnityEngine;
using UnityEngine.UI;

namespace Companion
{
    /// <summary>左侧视觉窗：青色全息 HUD。16:9 视频区，下方文字严格裁在框内。</summary>
    public class CameraMagnifier : MonoBehaviour
    {
        public CameraVision vision;
        public HandFocus hand;
        public float zoom = 2f;
        public bool Active { get; private set; }
        public bool autoOpenForTest = false;

        Canvas canvas;
        CanvasGroup group;
        RectTransform scanBar;
        Text dataText;
        Texture2D panelTex;
        RawImage view;
        Material mat;
        Renderer quadView;
        Material quadMat;
        Text noSignal;
        Text visionText;
        Texture2D blackTex;
        Coroutine anim;
        Vector3 baseScale = Vector3.one * 0.0009f;

        static readonly Color Hud = new Color(0.22f, 0.93f, 1f, 0.95f);
        static readonly Color HudDim = new Color(0.12f, 0.55f, 0.72f, 0.55f);
        static readonly Color Panel = new Color(0.008f, 0.035f, 0.055f, 0.68f);
        static readonly Color TextCol = new Color(0.72f, 0.96f, 1f, 0.96f);
        const float W = 480f, H = 360f;

        void Start()
        {
            Debug.Log("Magnifier start");
            var go = new GameObject("MagnifierCanvas");
            var cam = Camera.main;
            if (cam != null)
            {
                go.transform.SetParent(cam.transform, false);
                go.transform.localPosition = new Vector3(-0.41f, 0.00f, 0.78f);
                go.transform.localRotation = Quaternion.Euler(1f, -18f, -2.0f);
                go.transform.localScale = baseScale;
            }
            else
            {
                go.transform.SetParent(transform, false);
                go.transform.localPosition = new Vector3(0f, 1.50f, 0.80f);
                go.transform.localRotation = Quaternion.Euler(1f, -10f, -1.5f);
                go.transform.localScale = baseScale;
            }

            canvas = go.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.sortingOrder = 100;
            group = go.AddComponent<CanvasGroup>();
            var rt = go.GetComponent<RectTransform>();
            rt.sizeDelta = new Vector2(W, H);
            go.AddComponent<CanvasScaler>();
            go.AddComponent<GraphicRaycaster>();

            BuildPanel(go.transform);
            BuildFrame(go.transform);

            var scan = NewImage(go.transform, "ScanBar", new Color(0.55f, 1f, 1f, 0.38f), new Vector2(W - 40f, 3f), new Vector2(0f, H / 2f - 18f));
            scanBar = scan.rectTransform;
            scanBar.gameObject.SetActive(false);

            var dGo = new GameObject("DataText");
            dGo.transform.SetParent(go.transform, false);
            dataText = dGo.AddComponent<Text>();
            dataText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            dataText.fontSize = 11;
            dataText.color = new Color(0.3f, 0.95f, 1f, 0.9f);
            dataText.alignment = TextAnchor.LowerRight;
            dataText.raycastTarget = false;
            dataText.text = "";
            dataText.rectTransform.sizeDelta = new Vector2(220, 18);
            dataText.rectTransform.anchoredPosition = new Vector2(W / 2f - 126f, -H / 2f + 8f);

            var videoRoot = new GameObject("VideoRoot");
            videoRoot.transform.SetParent(go.transform, false);
            var vrr = videoRoot.AddComponent<RectTransform>();
            vrr.sizeDelta = new Vector2(432, 243);
            vrr.anchoredPosition = new Vector2(0, 34);

            var viewGo = new GameObject("View");
            viewGo.transform.SetParent(videoRoot.transform, false);
            view = viewGo.AddComponent<RawImage>();
            view.color = Color.white;
            var vrt = viewGo.GetComponent<RectTransform>();
            vrt.sizeDelta = new Vector2(432, 243);
            vrt.anchoredPosition = Vector2.zero;

            blackTex = new Texture2D(2, 2, TextureFormat.RGB24, false);
            blackTex.SetPixels(new[] { Color.black, Color.black, Color.black, Color.black });
            blackTex.Apply();
            view.texture = blackTex;

            var shader = Shader.Find("Companion/Magnifier");
            if (shader == null) shader = Shader.Find("UI/Default");
            if (shader == null) shader = Shader.Find("Unlit/Texture");
            if (shader != null) mat = new Material(shader);
            if (mat != null) view.material = mat;
            view.enabled = false;

            var nsGo = new GameObject("NoSignal");
            nsGo.transform.SetParent(videoRoot.transform, false);
            noSignal = nsGo.AddComponent<Text>();
            noSignal.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            noSignal.fontSize = 20;
            noSignal.color = new Color(0.45f, 0.78f, 0.9f, 0.8f);
            noSignal.alignment = TextAnchor.MiddleCenter;
            noSignal.text = "NO SIGNAL";
            noSignal.raycastTarget = false;
            nsGo.GetComponent<RectTransform>().sizeDelta = new Vector2(432, 243);

            AddLine(videoRoot.transform, "VT", new Vector2(0, 121.5f), 432, 1, HudDim);
            AddLine(videoRoot.transform, "VB", new Vector2(0, -121.5f), 432, 1, HudDim);
            AddLine(videoRoot.transform, "VL", new Vector2(-216, 0), 1, 243, HudDim);
            AddLine(videoRoot.transform, "VR", new Vector2(216, 0), 1, 243, HudDim);

            var textRoot = new GameObject("TextRoot");
            textRoot.transform.SetParent(go.transform, false);
            var trr = textRoot.AddComponent<RectTransform>();
            trr.sizeDelta = new Vector2(432, 72);
            trr.anchoredPosition = new Vector2(0, -118);

            var vGo = new GameObject("VisionText");
            vGo.transform.SetParent(textRoot.transform, false);
            visionText = vGo.AddComponent<Text>();
            visionText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            visionText.fontSize = 18;
            visionText.color = TextCol;
            visionText.alignment = TextAnchor.UpperLeft;
            visionText.horizontalOverflow = HorizontalWrapMode.Wrap;
            visionText.verticalOverflow = VerticalWrapMode.Truncate;
            visionText.raycastTarget = false;
            visionText.lineSpacing = 1.0f;
            visionText.text = "";
            var vrt2 = vGo.GetComponent<RectTransform>();
            vrt2.sizeDelta = new Vector2(424, 64);
            vrt2.anchoredPosition = Vector2.zero;

            var outline = visionText.gameObject.AddComponent<Outline>();
            outline.effectColor = new Color(0f, 0.08f, 0.12f, 0.9f);
            outline.effectDistance = new Vector2(1f, -1f);

            AddLabel(go.transform, "COMPANION // OPTIC", -222, 162, 15, TextAnchor.UpperLeft);
            AddLabel(go.transform, "● LIVE", 222, 162, 13, TextAnchor.UpperRight);

            var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
            quad.name = "CameraQuad";
            quad.transform.SetParent(go.transform, false);
            quad.transform.localPosition = new Vector3(0f, 34f, 0.6f);
            quad.transform.localRotation = Quaternion.identity;
            quad.transform.localScale = new Vector3(432f, 243f, 1f);
            var qs = Shader.Find("Unlit/Texture");
            if (qs == null) qs = Shader.Find("Sprites/Default");
            quadMat = new Material(qs);
            quad.GetComponent<MeshRenderer>().material = quadMat;
            quadView = quad.GetComponent<Renderer>();
            quad.SetActive(false);

            canvas.enabled = false;
            group.alpha = 0f;
            if (autoOpenForTest) Invoke(nameof(Toggle), 4f);
        }

        void BuildPanel(Transform parent)
        {
            int tw = (int)W, th = (int)H;
            panelTex = new Texture2D(tw, th, TextureFormat.RGBA32, false);
            panelTex.wrapMode = TextureWrapMode.Clamp;
            var px = new Color32[tw * th];
            float hw = W / 2f, hh = H / 2f, cut = 24f;
            for (int y = 0; y < th; y++)
            {
                for (int x = 0; x < tw; x++)
                {
                    float ax = Mathf.Abs(x - tw / 2f + 0.5f);
                    float ay = Mathf.Abs(y - th / 2f + 0.5f);
                    bool inside = ax <= hw && ay <= hh &&
                        (ax <= hw - cut || ay <= hh - cut || (ax - (hw - cut)) + (ay - (hh - cut)) <= cut);
                    px[y * tw + x] = inside ? (Color32)Panel : new Color32(0, 0, 0, 0);
                }
            }
            panelTex.SetPixels32(px);
            panelTex.Apply();
            var bgGo = new GameObject("Bg");
            bgGo.transform.SetParent(parent, false);
            var bg = bgGo.AddComponent<RawImage>();
            bg.texture = panelTex;
            bg.raycastTarget = false;
            var brt = bgGo.GetComponent<RectTransform>();
            brt.sizeDelta = new Vector2(W, H);
            brt.anchoredPosition = Vector2.zero;
        }

        void BuildFrame(Transform parent)
        {
            float hw = W / 2f, hh = H / 2f, cut = 24f;
            AddLine(parent, "GT", new Vector2(0, hh), W - cut * 2, 6, new Color(Hud.r, Hud.g, Hud.b, 0.12f));
            AddLine(parent, "GB", new Vector2(0, -hh), W - cut * 2, 6, new Color(Hud.r, Hud.g, Hud.b, 0.12f));
            AddLine(parent, "GL", new Vector2(-hw, 0), 6, H - cut * 2, new Color(Hud.r, Hud.g, Hud.b, 0.12f));
            AddLine(parent, "GR", new Vector2(hw, 0), 6, H - cut * 2, new Color(Hud.r, Hud.g, Hud.b, 0.12f));

            AddLine(parent, "T", new Vector2(0, hh), W - cut * 2, 2, Hud);
            AddLine(parent, "B", new Vector2(0, -hh), W - cut * 2, 2, Hud);
            AddLine(parent, "L", new Vector2(-hw, 0), 2, H - cut * 2, Hud);
            AddLine(parent, "R", new Vector2(hw, 0), 2, H - cut * 2, Hud);

            AddLine(parent, "C1", new Vector2(-hw + cut / 2f, hh - cut / 2f), cut * 1.414f, 2, Hud, 45f);
            AddLine(parent, "C2", new Vector2(hw - cut / 2f, hh - cut / 2f), cut * 1.414f, 2, Hud, -45f);
            AddLine(parent, "C3", new Vector2(-hw + cut / 2f, -hh + cut / 2f), cut * 1.414f, 2, Hud, -45f);
            AddLine(parent, "C4", new Vector2(hw - cut / 2f, -hh + cut / 2f), cut * 1.414f, 2, Hud, 45f);

            AddLine(parent, "TC1", new Vector2(-hw + 46, hh - 10), 24, 2, Hud);
            AddLine(parent, "TC2", new Vector2(hw - 46, hh - 10), 24, 2, Hud);
            AddLine(parent, "BC1", new Vector2(-hw + 46, -hh + 10), 24, 2, Hud);
            AddLine(parent, "BC2", new Vector2(hw - 46, -hh + 10), 24, 2, Hud);
            AddLine(parent, "Header", new Vector2(0, 140), W - 56, 1, HudDim);
        }

        void AddLine(Transform parent, string name, Vector2 pos, float w, float h, Color color, float rot = 0f)
        {
            var img = NewImage(parent, name, color, new Vector2(w, h), pos);
            img.rectTransform.localRotation = Quaternion.Euler(0, 0, rot);
        }

        Image NewImage(Transform parent, string name, Color color, Vector2 size, Vector2 pos)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var img = go.AddComponent<Image>();
            img.color = color;
            img.raycastTarget = false;
            var rt = go.GetComponent<RectTransform>();
            rt.sizeDelta = size;
            rt.anchoredPosition = pos;
            return img;
        }

        void AddLabel(Transform parent, string text, float x, float y, int size, TextAnchor anchor)
        {
            var go = new GameObject("Label");
            go.transform.SetParent(parent, false);
            var t = go.AddComponent<Text>();
            t.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            t.fontSize = size;
            t.color = TextCol;
            t.alignment = anchor;
            t.horizontalOverflow = HorizontalWrapMode.Overflow;
            t.verticalOverflow = VerticalWrapMode.Overflow;
            t.raycastTarget = false;
            t.text = text;
            var rt = go.GetComponent<RectTransform>();
            rt.sizeDelta = new Vector2(300, 20);
            rt.anchoredPosition = new Vector2(x, y);
        }

        public void Toggle()
        {
            Active = !Active;
            if (canvas != null) canvas.enabled = true;
            if (quadView != null) quadView.gameObject.SetActive(Active);
            if (vision != null) vision.SetFastMode(Active);
            if (anim != null) StopCoroutine(anim);
            anim = StartCoroutine(Animate(Active));
            Debug.Log("Magnifier " + (Active ? "on" : "off"));
        }

        System.Collections.IEnumerator Animate(bool open)
        {
            float t = 0f, dur = 0.34f;
            Vector3 from = open ? new Vector3(baseScale.x * 0.02f, baseScale.y, baseScale.z) : baseScale;
            Vector3 to = open ? baseScale : new Vector3(baseScale.x * 0.02f, baseScale.y, baseScale.z);
            float a0 = open ? 0f : 1f, a1 = open ? 1f : 0f;
            if (scanBar != null) scanBar.gameObject.SetActive(true);
            while (t < dur)
            {
                t += Time.deltaTime;
                float k = Mathf.Clamp01(t / dur);
                float e = 1f - Mathf.Pow(1f - k, 3f);
                canvas.transform.localScale = Vector3.Lerp(from, to, e);
                float flicker = (1f - k) * (open ? 0.25f : 0.35f);
                group.alpha = Mathf.Clamp01(Mathf.Lerp(a0, a1, k) + Mathf.Sin(t * 95f) * flicker);
                if (scanBar != null)
                {
                    float sy = Mathf.Lerp(H / 2f - 18f, -H / 2f + 18f, k);
                    scanBar.anchoredPosition = new Vector2(0f, sy);
                }
                if (dataText != null)
                {
                    dataText.text = "SYNC 0x" + Random.Range(0x1000, 0xFFFF).ToString("X4") + "  //  " +
                                    Mathf.FloorToInt(k * 100f).ToString("D3") + "%";
                }
                yield return null;
            }
            canvas.transform.localScale = to;
            group.alpha = a1;
            if (scanBar != null) scanBar.gameObject.SetActive(false);
            if (dataText != null && open) dataText.text = "SYNC OK  //  100%";
            if (!open) canvas.enabled = false;
        }

        void Update()
        {
            if (!Active || mat == null) return;
            bool freshPreview = vision != null && vision.HasFreshPreview(30f);
            if (freshPreview)
            {
                if (hand != null) vision.SetFocus(hand.PointerUV.x, hand.PointerUV.y);
                if (quadMat != null)
                {
                    quadMat.mainTexture = vision.PreviewTexture;
                    quadMat.mainTextureScale = Vector2.one;
                    quadMat.mainTextureOffset = Vector2.zero;
                }
                if (visionText != null)
                {
                    // 识图结果也只活 30 秒；旧画面不能继续当作“现在看到的”
                    string s = vision.HasFreshVision(30f) ? (vision.LastVisionText ?? "") : "";
                    if (s.Length > 200) s = s.Substring(0, 200);
                    visionText.text = string.IsNullOrEmpty(s) ? "视觉识别中…" : s;
                }
                if (noSignal != null) noSignal.enabled = false;
            }
            else
            {
                if (noSignal != null) noSignal.enabled = true;
                if (visionText != null) visionText.text = "视觉信号等待中…";
            }
            if (hand != null)
                mat.SetVector("_Center", new Vector4(hand.PointerUV.x, hand.PointerUV.y, 0, 0));
            mat.SetFloat("_Zoom", zoom);
        }
    }
}
