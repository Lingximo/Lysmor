using System.Collections;
using UnityEngine;
using UnityEngine.XR;
using Unity.XR.PXR;

namespace Companion
{
    /// <summary>固定世界位置的全息球：
    /// 和手使用同一个世界坐标；手靠近自动抓，停住可开关窗。</summary>
    public class HoloSphereController : MonoBehaviour
    {
        public CameraMagnifier magnifier;
        public Vector3 home = new Vector3(0.28f, -0.24f, 0.48f); // 相机局部坐标：右 0.28m，下 0.24m，前 0.48m
        public float radius = 0.045f;
        public float grabDistance = 0.50f;
        public float holdToToggle = 2.0f;
        public float returnTime = 0.45f;

        Transform headAnchor;
        Vector3 headPos;
        Quaternion headRot = Quaternion.identity;
        Transform root;
        Transform core;
        Transform shell;
        Transform ringA;
        Transform ringB;
        Transform ringInner;
        Material coreMat;
        Material shellMat;
        Material ringMat;
        Material ringBMat;
        Material ringInnerMat;
        Transform holoOuter;
        Transform holoInner;
        Material holoOuterMat;
        Material holoInnerMat;
        Texture2D ringStripe;
        PXR_Hand handRoot;
        HandJointLocations joints;
        HandAimState aim;
        bool grabbing;
        bool returning;
        bool fistWasDown;
        bool toggledThisHold;
        float fistDownAt;
        float returnAt;
        Vector3 grabOffset;
        Vector3 returnFrom;
        Vector3 returnTo;
        float pulse;

        void Start()
        {
            handRoot = FindObjectOfType<PXR_Hand>(true);
            Build();
        }

        void Build()
        {
            var cam = Camera.main;
            headAnchor = new GameObject("HoloHeadAnchor").transform;
            if (cam != null) headAnchor.SetParent(cam.transform, false);
            root = new GameObject("HoloSphereRoot").transform;
            root.SetParent(headAnchor, false);
            root.localPosition = home;

            var coreGo = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            coreGo.name = "HoloCore";
            coreGo.transform.SetParent(root, false);
            coreGo.transform.localPosition = new Vector3(0f, 0f, -0.012f);
            coreGo.transform.localScale = Vector3.one * radius * 2.0f;
            Destroy(coreGo.GetComponent<Collider>());
            core = coreGo.transform;

            var shader = Shader.Find("Standard");
            if (shader == null) shader = Shader.Find("Unlit/Color");
            coreMat = new Material(shader);
            // 中心：淡蓝实体球，正面遮住全息盘中心
            coreMat.color = new Color(0.48f, 0.78f, 1f, 1f);
            coreMat.EnableKeyword("_EMISSION");
            coreMat.SetColor("_EmissionColor", new Color(0.25f, 0.55f, 1f) * 0.8f);
            coreMat.SetFloat("_Metallic", 0.10f);
            coreMat.SetFloat("_Glossiness", 0.95f);
            coreGo.GetComponent<Renderer>().material = coreMat;

            var shellGo = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            shellGo.name = "HoloShell";
            shellGo.transform.SetParent(root, false);
            shellGo.transform.localPosition = new Vector3(0f, 0f, -0.012f);
            shellGo.transform.localScale = Vector3.one * radius * 2.55f;
            Destroy(shellGo.GetComponent<Collider>());
            shell = shellGo.transform;
            shellMat = new Material(shader);
            shellMat.color = new Color(0.55f, 0.82f, 1f, 0.14f);
            shellMat.SetFloat("_Mode", 3f);
            shellMat.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.One);
            shellMat.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.One);
            shellMat.SetInt("_ZWrite", 0);
            shellMat.DisableKeyword("_ALPHATEST_ON");
            shellMat.EnableKeyword("_ALPHABLEND_ON");
            shellMat.DisableKeyword("_ALPHAPREMULTIPLY_ON");
            shellMat.renderQueue = 3000;
            shellGo.GetComponent<Renderer>().material = shellMat;

            // 复杂全息盘：内层橙环 + 外层红白环 + 青蓝弧
            holoOuter = MakeHoloPlate("HoloOuter", radius * 7.0f, true, -0.012f);
            holoInner = MakeHoloPlate("HoloInner", radius * 2.6f, false, -0.012f);
        }

        Texture2D MakeRingStripe()
        {
            const int n = 32;
            var tex = new Texture2D(n, 2, TextureFormat.RGBA32, false);
            var px = new Color[n * 2];
            for (int y = 0; y < 2; y++)
            for (int x = 0; x < n; x++)
                px[y * n + x] = x < 19 ? Color.white : new Color(1f, 1f, 1f, 0f);
            tex.SetPixels(px);
            tex.wrapMode = TextureWrapMode.Repeat;
            tex.filterMode = FilterMode.Bilinear;
            tex.Apply();
            return tex;
        }

        Transform MakeRing(string name, float r)
        {
            var go = new GameObject(name);
            go.transform.SetParent(root, false);
            var lr = go.AddComponent<LineRenderer>();
            lr.useWorldSpace = false;
            lr.loop = true;
            lr.positionCount = 48;
            lr.startWidth = 0.0045f;
            lr.endWidth = 0.0045f;
            lr.textureMode = LineTextureMode.Tile;
            lr.material = ringMat;
            lr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            lr.receiveShadows = false;
            for (int i = 0; i < 48; i++)
            {
                float a = i / 48f * Mathf.PI * 2f;
                lr.SetPosition(i, new Vector3(Mathf.Cos(a) * r, Mathf.Sin(a) * r, 0f));
            }
            return go.transform;
        }

        Transform MakeHoloPlate(string name, float size, bool outer, float z)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Quad);
            go.name = name;
            Destroy(go.GetComponent<Collider>());
            go.transform.SetParent(root, false);
            go.transform.localPosition = new Vector3(0f, 0f, z);
            go.transform.localScale = Vector3.one * size;

            var shader = Shader.Find("Sprites/Default");
            if (shader == null) shader = Shader.Find("Unlit/Transparent");
            var mat = new Material(shader);
            mat.mainTexture = MakeHoloTexture(outer);
            mat.color = Color.white;
            mat.renderQueue = 3100;
            var rend = go.GetComponent<Renderer>();
            rend.material = mat;
            rend.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            rend.receiveShadows = false;
            if (outer) holoOuterMat = mat; else holoInnerMat = mat;
            return go.transform;
        }

        Texture2D MakeHoloTexture(bool outer)
        {
            const int S = 512;
            const float PI = Mathf.PI;
            float c = S * 0.5f;
            var px = new Color[S * S];

            Color orange = new Color(1.0f, 0.30f, 0.035f, 1f);
            Color amber  = new Color(1.0f, 0.56f, 0.10f, 1f);
            Color hot    = new Color(1.0f, 0.93f, 0.70f, 1f);
            Color red    = new Color(0.70f, 0.035f, 0.015f, 1f);
            Color cyan   = new Color(0.18f, 0.82f, 1.0f, 1f);
            Color blue   = new Color(0.08f, 0.30f, 0.95f, 1f);

            void Blend(int x, int y, Color col)
            {
                if (x < 0 || y < 0 || x >= S || y >= S || col.a <= 0f) return;
                int i = y * S + x;
                var b = px[i];
                float a = col.a;
                px[i] = new Color(col.r * a + b.r * (1f - a),
                                  col.g * a + b.g * (1f - a),
                                  col.b * a + b.b * (1f - a),
                                  Mathf.Max(b.a, a));
            }

            void Disc(float radius, Color col, float soft = 2f)
            {
                int x0 = Mathf.Max(0, (int)(c - radius - soft));
                int x1 = Mathf.Min(S - 1, (int)(c + radius + soft));
                for (int y = x0; y <= x1; y++)
                for (int x = x0; x <= x1; x++)
                {
                    float d = Mathf.Sqrt((x - c) * (x - c) + (y - c) * (y - c));
                    if (d > radius + soft) continue;
                    float a = col.a * Mathf.Clamp01((radius + soft - d) / (soft + 0.001f));
                    Blend(x, y, new Color(col.r, col.g, col.b, a));
                }
            }

            void Ring(float radius, float width, Color col, int segs = 0, float gap = 0.16f)
            {
                float outerR = radius + width * 0.5f + 1f;
                int x0 = Mathf.Max(0, (int)(c - outerR));
                int x1 = Mathf.Min(S - 1, (int)(c + outerR));
                for (int y = x0; y <= x1; y++)
                for (int x = x0; x <= x1; x++)
                {
                    float dx = x - c, dy = y - c;
                    float d = Mathf.Sqrt(dx * dx + dy * dy);
                    float a = Mathf.Clamp01((width * 0.5f + 1f - Mathf.Abs(d - radius)) / 1.5f);
                    if (a <= 0f) continue;
                    if (segs > 0)
                    {
                        float ang = (Mathf.Atan2(dy, dx) + PI) / (2f * PI);
                        float f = ang * segs;
                        if (f - Mathf.Floor(f) < gap) continue;
                    }
                    Blend(x, y, new Color(col.r, col.g, col.b, col.a * a));
                }
            }

            void Arc(float radius, float width, float a0, float a1, Color col)
            {
                int x0 = Mathf.Max(0, (int)(c - radius - width));
                int x1 = Mathf.Min(S - 1, (int)(c + radius + width));
                for (int y = x0; y <= x1; y++)
                for (int x = x0; x <= x1; x++)
                {
                    float dx = x - c, dy = y - c;
                    float d = Mathf.Sqrt(dx * dx + dy * dy);
                    if (Mathf.Abs(d - radius) > width * 0.5f) continue;
                    float ang = Mathf.Atan2(dy, dx);
                    if (ang < a0 || ang > a1) continue;
                    Blend(x, y, col);
                }
            }

            void Spoke(float angle, float r0, float r1, Color col)
            {
                int steps = Mathf.Max(8, (int)(r1 - r0));
                for (int i = 0; i <= steps; i++)
                {
                    float r = Mathf.Lerp(r0, r1, i / (float)steps);
                    int x = Mathf.RoundToInt(c + Mathf.Cos(angle) * r);
                    int y = Mathf.RoundToInt(c + Mathf.Sin(angle) * r);
                    Blend(x, y, col);
                    Blend(x + 1, y, col);
                }
            }

            if (outer)
            {
                // 红色底光 + 中轴能量
                Disc(0.72f * c, new Color(1f, 0.03f, 0.008f, 0.08f), 36f);
                Disc(0.34f * c, new Color(0.10f, 0.008f, 0.002f, 0.45f), 20f);

                // 中心橙白核心
                Ring(0.15f * c, 0.018f * c, hot);
                Ring(0.21f * c, 0.040f * c, orange, 18, 0.34f);
                Ring(0.29f * c, 0.055f * c, red, 22, 0.28f);
                Ring(0.29f * c, 0.030f * c, amber, 22, 0.60f);

                // 外层黑白/红分段环
                Ring(0.43f * c, 0.085f * c, new Color(0.16f, 0.025f, 0.015f, 0.85f), 26, 0.18f);
                Ring(0.43f * c, 0.060f * c, new Color(0.95f, 0.88f, 0.72f, 0.95f), 26, 0.48f);
                Ring(0.53f * c, 0.022f * c, orange, 20, 0.30f);
                Ring(0.59f * c, 0.012f * c, red);

                // 青蓝外弧与节点
                Arc(0.74f * c, 0.018f * c, -2.75f, -1.05f, cyan);
                Arc(0.78f * c, 0.010f * c, -0.52f, 0.82f, cyan);
                Arc(0.82f * c, 0.008f * c, 1.20f, 2.35f, blue);
                Arc(0.68f * c, 0.012f * c, -2.95f, -2.40f, hot);
                for (int i = 0; i < 7; i++)
                {
                    float a = -2.7f + i * 0.52f;
                    Disc(0.95f * c, new Color(0.02f, 0.02f, 0.02f, 0f));
                    int nx = Mathf.RoundToInt(c + Mathf.Cos(a) * 0.76f * c);
                    int ny = Mathf.RoundToInt(c + Mathf.Sin(a) * 0.76f * c);
                    Blend(nx, ny, cyan);
                    Blend(nx + 1, ny, cyan);
                }

                // 红色电路辐条
                for (int i = 0; i < 30; i++)
                {
                    float a = i / 30f * PI * 2f + 0.11f;
                    if (i % 5 == 0) Spoke(a, 0.20f * c, 0.86f * c, new Color(0.25f, 0.85f, 1f, 0.85f));
                    else if (i % 3 == 0) Spoke(a, 0.26f * c, 0.70f * c, new Color(1f, 0.34f, 0.06f, 0.55f));
                }

                // 横向高光，模仿图中的反光玻璃
                for (int i = -4; i <= 4; i++)
                {
                    float y = c + i * 0.055f * c;
                    for (int x = (int)(0.25f * c); x < (int)(0.75f * c); x++)
                        Blend(x, (int)y, new Color(1f, 0.85f, 0.62f, 0.05f));
                }
            }
            else
            {
                // 内层：橙色日冕/齿环，反向旋转
                Disc(0.34f * c, new Color(0.18f, 0.012f, 0.003f, 0.16f), 20f);
                Ring(0.18f * c, 0.020f * c, hot);
                Ring(0.24f * c, 0.050f * c, red, 16, 0.26f);
                Ring(0.24f * c, 0.024f * c, amber, 16, 0.62f);
                Ring(0.32f * c, 0.028f * c, orange, 20, 0.30f);
                Ring(0.36f * c, 0.010f * c, new Color(1f, 0.55f, 0.10f, 0.7f));
                for (int i = 0; i < 16; i++)
                {
                    float a = i / 16f * PI * 2f;
                    Spoke(a, 0.18f * c, 0.31f * c, new Color(1f, 0.48f, 0.08f, 0.45f));
                }
            }

            var tex = new Texture2D(S, S, TextureFormat.RGBA32, false);
            tex.wrapMode = TextureWrapMode.Clamp;
            tex.filterMode = FilterMode.Bilinear;
            tex.SetPixels(px);
            tex.Apply();
            try
            {
                var path = System.IO.Path.Combine(Application.persistentDataPath, outer ? "holo_outer.png" : "holo_inner.png");
                System.IO.File.WriteAllBytes(path, tex.EncodeToPNG());
            }
            catch { }
            return tex;
        }

        float nextLog;


        void Update()
        {
            if (root == null) return;
            UpdateHeadAnchor();
            FaceHolo();

            Vector3 handPos = Vector3.zero;
            bool hasHand = TryGetHandPos(out handPos);
            float fistAvg = 0f;
            bool fist = hasHand && PXRHandGesture.TryGetFist(HandType.HandRight, out fistAvg);
            bool pinch = PXR_HandTracking.GetAimState(HandType.HandRight, ref aim)
                         && (((aim.aimStatus & HandAimStatus.AimIndexPinching) != 0) || aim.touchStrengthRay > 0.55f);
            bool near = hasHand && Vector3.Distance(handPos, root.localPosition) <= grabDistance;
            bool grabInput = fist || pinch;
            if (hasHand && Time.time > nextLog)
            {
                nextLog = Time.time + 1f;
                Debug.Log($"HoloSphere head={headAnchor.localPosition} cam={Camera.main.transform.position} hand={handPos} sphere={root.localPosition} dist={Vector3.Distance(handPos, root.localPosition):F2} fist={fist} pinch={pinch} near={near} avg={fistAvg:F3}");
            }

            if (grabInput && !fistWasDown)
            {
                fistDownAt = Time.time;
                toggledThisHold = false;
                if (hasHand && Vector3.Distance(handPos, root.localPosition) <= grabDistance)
                {
                    grabbing = true;
                    returning = false;
                    grabOffset = root.localPosition - handPos;
                }
            }

            if (grabInput && hasHand)
            {
                if (grabbing)
                {
                    var target = handPos + grabOffset;
                    target.z = Mathf.Max(0.35f, target.z);
                    root.localPosition = Vector3.Lerp(root.localPosition, target, 1f - Mathf.Exp(-18f * Time.deltaTime));
                    pulse = Mathf.Lerp(pulse, 1f, 1f - Mathf.Exp(-12f * Time.deltaTime));
                }

                // 握拳 2 秒切换一次；同一次握拳不重复触发
                if ((fist || pinch) && !toggledThisHold && Time.time - fistDownAt >= holdToToggle)
                {
                    toggledThisHold = true;
                    pulse = 1.6f;
                    if (magnifier != null) magnifier.Toggle();
                    Debug.Log("HoloSphere: window toggle once per hold");
                }
            }

            if (!grabInput && fistWasDown)
            {
                if (grabbing)
                {
                    grabbing = false;
                    StartReturn();
                }
                toggledThisHold = false;
            }
            fistWasDown = grabInput;

            if (returning)
            {
                float k = Mathf.Clamp01((Time.time - returnAt) / returnTime);
                k = 1f - Mathf.Pow(1f - k, 3f);
                root.localPosition = Vector3.Lerp(returnFrom, returnTo, k);
                if (k >= 1f) returning = false;
            }

            // 呼吸 + 抓取反应
            float breathe = 1f + Mathf.Sin(Time.time * 2.2f) * 0.035f;
            float targetScale = grabbing ? 1.22f : breathe;
            core.localScale = Vector3.Lerp(core.localScale, Vector3.one * radius * 2.0f * targetScale, 1f - Mathf.Exp(-10f * Time.deltaTime));
            if (shell != null)
                shell.localScale = Vector3.Lerp(shell.localScale, Vector3.one * radius * 2.55f * targetScale, 1f - Mathf.Exp(-8f * Time.deltaTime));

            float glow = 1.5f + Mathf.Sin(Time.time * 2.2f) * 0.25f + (grabbing ? 0.9f : 0f) + pulse;
            if (coreMat != null)
                coreMat.SetColor("_EmissionColor", new Color(0.25f, 0.55f, 1f) * glow * 0.65f);
            if (ringMat != null)
                ringMat.color = new Color(1f, 0.38f, 0.05f, grabbing ? 1f : 0.9f);
            if (ringBMat != null)
                ringBMat.color = new Color(0.25f, 0.85f, 1f, grabbing ? 1f : 0.8f);
            if (ringInnerMat != null)
                ringInnerMat.color = new Color(1f, 0.65f, 0.12f, 1f);

            var rend = core != null ? core.GetComponent<Renderer>() : null;
            if (rend != null && Time.time > nextLog) Debug.Log($"HoloSphere visible={rend.isVisible} pos={root.localPosition}");
            if (holoOuter != null)
            {
                holoOuter.Rotate(0f, 0f, (grabbing ? 78f : 20f) * Time.deltaTime, Space.Self);
                holoInner.Rotate(0f, 0f, (grabbing ? -115f : -32f) * Time.deltaTime, Space.Self);
                float hs = 1f + Mathf.Sin(Time.time * 2.6f) * 0.025f + (grabbing ? 0.035f : 0f);
                holoOuter.localScale = Vector3.one * (radius * 7.0f * hs);
                holoInner.localScale = Vector3.one * (radius * 2.6f * hs);
                if (holoOuterMat != null)
                    holoOuterMat.color = new Color(1f, 1f, 1f, 0.82f + Mathf.Sin(Time.time * 11f) * 0.08f);
                if (holoInnerMat != null)
                    holoInnerMat.color = new Color(1f, 1f, 1f, 0.88f + Mathf.Sin(Time.time * 9f + 1.7f) * 0.10f);
            }

            pulse = Mathf.MoveTowards(pulse, 0f, Time.deltaTime * 2.2f);
        }

        void FaceHolo()
        {
            if (holoOuter == null) return;
            Vector3 eye = headPos.sqrMagnitude > 0.0025f ? headPos : (Camera.main != null ? Camera.main.transform.position : Vector3.zero);
            Vector3 dir = holoOuter.position - eye;
            if (dir.sqrMagnitude < 0.0001f) return;
            var q = Quaternion.LookRotation(dir, Vector3.up);
            holoOuter.rotation = q;
            holoInner.rotation = q;
        }

        void UpdateHeadAnchor()
        {
            if (headAnchor == null) return;
            var hp = InputTracking.GetLocalPosition(XRNode.Head);
            var hr = InputTracking.GetLocalRotation(XRNode.Head);
            if (hp.sqrMagnitude <= 0.0025f) return;
            headPos = hp;
            headRot = hr;
            // 球本身固定屏幕位置，不跟着头在世界里移动
            headAnchor.localPosition = Vector3.zero;
            headAnchor.localRotation = Quaternion.identity;
        }

        bool TryGetHandPos(out Vector3 pos)
        {
            pos = Vector3.zero;
            // 优先用 PXR 关节世界坐标，再减去实时头高，换算到镜头空间
            if (PXR_HandTracking.GetJointLocations(HandType.HandRight, ref joints) && joints.jointLocations != null)
            {
                int palm = (int)HandJoint.JointPalm;
                if (palm < joints.jointLocations.Length)
                {
                    var wp = joints.jointLocations[palm].pose.Position.ToVector3();
                    var p = Quaternion.Inverse(headRot) * (wp - headPos);
                    if (p.sqrMagnitude > 0.0025f)
                    {
                        pos = p;
                        return true;
                    }
                }
            }
            // 兜底：手关节 localPosition（部分 PXR 版本只更新 local）
            if (handRoot != null && handRoot.handJoints != null)
            {
                int palm = (int)HandJoint.JointPalm;
                if (palm < handRoot.handJoints.Count && handRoot.handJoints[palm] != null)
                {
                    var wp = handRoot.transform.TransformPoint(handRoot.handJoints[palm].localPosition);
                    pos = Quaternion.Inverse(headRot) * (wp - headPos);
                    return pos.sqrMagnitude > 0.0025f;
                }
            }
            return false;
        }

        void StartReturn()
        {
            returning = true;
            returnAt = Time.time;
            returnFrom = root.localPosition;
            returnTo = home;
        }
    }
}
