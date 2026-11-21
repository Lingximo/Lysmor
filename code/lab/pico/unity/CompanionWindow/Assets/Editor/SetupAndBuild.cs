using System.IO;
using System.Linq;
using System.Xml;
using Unity.XR.PXR;
using UnityEditor;
using UnityEditor.Android;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR.Management;

namespace Companion.Editor
{
    /// <summary>
    /// 一次性配置工程并打出浮窗 APK。
    /// </summary>
    public static class SetupAndBuild
    {
        const string ScenePath = "Assets/Scenes/Main.unity";
        const string ApkPath = @"D:\dev\companion-window.apk";
        const string ProbeScenePath = "Assets/Scenes/Probe.unity";
        const string ProbeApkPath = @"D:\dev\companion-probe.apk";

        public static void Build()
        {
            ConfigureXR();
            ConfigurePlayer();
            BuildNativeScene();
            BuildApk();
        }

        /// <summary>只做相机探针，不开透视、不连语音，避免被系统设置页挡住。</summary>
        public static void Probe()
        {
            ConfigureXR();
            var probeCfg = PXR_ProjectSetting.GetProjectConfig();
            probeCfg.videoSeeThrough = false;
            probeCfg.stageMode = false;
            probeCfg.handTracking = false;
            EditorUtility.SetDirty(probeCfg);
            ConfigurePlayer();
            Directory.CreateDirectory("Assets/Scenes");
            var scene = UnityEditor.SceneManagement.EditorSceneManager.NewScene(
                UnityEditor.SceneManagement.NewSceneSetup.EmptyScene,
                UnityEditor.SceneManagement.NewSceneMode.Single);
            var xrRoot = new GameObject("XR Origin");
            var camOffset = new GameObject("Camera Offset");
            camOffset.transform.SetParent(xrRoot.transform, false);

            var camGo = new GameObject("Main Camera");
            camGo.transform.SetParent(camOffset.transform, false);
            camGo.transform.localPosition = Vector3.zero;
            camGo.transform.localRotation = Quaternion.identity;
            camGo.tag = "MainCamera";
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = Color.black;
            camGo.AddComponent<AudioListener>();
            camGo.AddComponent<PXR_Manager>();
            camGo.AddComponent<CameraProbe>();
            camGo.AddComponent<CameraVision>();
            UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, ProbeScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ProbeScenePath, true) };

            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = new[] { ProbeScenePath },
                locationPathName = ProbeApkPath,
                target = BuildTarget.Android,
                options = BuildOptions.None,
            });
            Debug.Log($"PROBE BUILD: {report.summary.result} -> {ProbeApkPath}");
            if (report.summary.result != BuildResult.Succeeded)
                throw new System.Exception("Probe build failed: " + report.summary.result);
        }

        static void ConfigureXR()
        {
            var buildTargetSettings = AssetDatabase
                .FindAssets("t:XRGeneralSettingsPerBuildTarget")
                .Select(guid => AssetDatabase.LoadAssetAtPath<XRGeneralSettingsPerBuildTarget>(
                    AssetDatabase.GUIDToAssetPath(guid)))
                .FirstOrDefault();

            if (buildTargetSettings == null)
            {
                buildTargetSettings = ScriptableObject.CreateInstance<XRGeneralSettingsPerBuildTarget>();
                AssetDatabase.CreateAsset(buildTargetSettings, "Assets/XRGeneralSettingsPerBuildTarget.asset");
            }

            var generalSettings = buildTargetSettings.SettingsForBuildTarget(BuildTargetGroup.Android);
            if (generalSettings == null)
            {
                generalSettings = ScriptableObject.CreateInstance<XRGeneralSettings>();
                AssetDatabase.AddObjectToAsset(generalSettings, buildTargetSettings);
                buildTargetSettings.SetSettingsForBuildTarget(BuildTargetGroup.Android, generalSettings);

                var managerSettings = ScriptableObject.CreateInstance<XRManagerSettings>();
                AssetDatabase.AddObjectToAsset(managerSettings, buildTargetSettings);
                generalSettings.Manager = managerSettings;
                EditorUtility.SetDirty(buildTargetSettings);
                AssetDatabase.SaveAssets();
            }

            if (generalSettings.Manager != null)
            {
                while (generalSettings.Manager.activeLoaders.Count > 0)
                {
                    var loaderName = generalSettings.Manager.activeLoaders[0].GetType().FullName;
                    XRPackageMetadataStore.RemoveLoader(generalSettings.Manager, loaderName, BuildTargetGroup.Android);
                }
                XRPackageMetadataStore.AssignLoader(generalSettings.Manager, "PXR_Loader", BuildTargetGroup.Android);
            }

            if (EditorBuildSettings.TryGetConfigObject("Unity.XR.PXR.Settings", out PXR_Settings _) == false)
            {
                var pxr = ScriptableObject.CreateInstance<PXR_Settings>();
                AssetDatabase.CreateAsset(pxr, "Assets/PXR_Settings.asset");
                EditorBuildSettings.AddConfigObject("Unity.XR.PXR.Settings", pxr, true);
            }

            // 手部追踪：应用声明支持，系统就不会把手柄当唯一输入
            var cfg = PXR_ProjectSetting.GetProjectConfig();
            cfg.handTracking = true;
            cfg.videoSeeThrough = true;
            cfg.stageMode = false;
            EditorUtility.SetDirty(cfg);
        }

        static void ConfigurePlayer()
        {
            EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Android, BuildTarget.Android);
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
            PlayerSettings.companyName = "Companion";
            PlayerSettings.productName = "CompanionWindow";
            PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Android, "com.companion.window");
            PlayerSettings.SetScriptingBackend(NamedBuildTarget.Android, ScriptingImplementation.IL2CPP);
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel29;
            PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevel33;
            PlayerSettings.Android.forceInternetPermission = true;
            PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, new[] { UnityEngine.Rendering.GraphicsDeviceType.OpenGLES3 });
            PlayerSettings.colorSpace = ColorSpace.Linear;
            PlayerSettings.defaultInterfaceOrientation = UIOrientation.LandscapeLeft;
        }

        static void BuildScene()
        {
            Directory.CreateDirectory("Assets/Scenes");
            var scene = UnityEditor.SceneManagement.EditorSceneManager.NewScene(
                UnityEditor.SceneManagement.NewSceneSetup.EmptyScene,
                UnityEditor.SceneManagement.NewSceneMode.Single);

            var camGo = new GameObject("Main Camera");
            camGo.tag = "MainCamera";
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0f, 0f, 0f, 0f);
            cam.nearClipPlane = 0.05f;
            cam.farClipPlane = 200f;
            camGo.AddComponent<AudioListener>();
            camGo.AddComponent<PXR_Manager>();
            camGo.AddComponent<Passthrough>();
            camGo.AddComponent<VoiceClient>();
            camGo.AddComponent<CameraProbe>();
            camGo.AddComponent<CameraVision>();

            var canvasGo = new GameObject("WindowCanvas");
            canvasGo.transform.position = new Vector3(0.35f, 1.6f, 1.2f);
            var canvas = canvasGo.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            var rt = canvasGo.GetComponent<RectTransform>();
            rt.sizeDelta = new Vector2(1280, 720);
            canvasGo.transform.localScale = Vector3.one * 0.00055f;
            canvasGo.AddComponent<CanvasScaler>();
            canvasGo.AddComponent<GraphicRaycaster>();
            canvasGo.AddComponent<FloatingWindow>();

            var panelGo = new GameObject("Panel");
            panelGo.transform.SetParent(canvasGo.transform, false);
            var raw = panelGo.AddComponent<RawImage>();
            raw.color = Color.white;
            var keyMat = new Material(Shader.Find("Companion/KeyedUI"));
            raw.material = keyMat;
            var prt = panelGo.GetComponent<RectTransform>();
            prt.sizeDelta = new Vector2(1280, 720);
            prt.anchoredPosition = Vector2.zero;

            var client = panelGo.AddComponent<MjpegClient>();
            client.target = raw;
            client.url = "http://YOUR-PC.local:8014/panel.mjpg";

            var capGo = new GameObject("Caption");
            capGo.transform.SetParent(canvasGo.transform, false);
            var caption = capGo.AddComponent<Text>();
            caption.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            caption.fontSize = 30;
            caption.color = new Color(0.85f, 0.97f, 1f);
            caption.alignment = TextAnchor.LowerLeft;
            caption.horizontalOverflow = HorizontalWrapMode.Wrap;
            caption.verticalOverflow = VerticalWrapMode.Overflow;
            var capRt = capGo.GetComponent<RectTransform>();
            capRt.sizeDelta = new Vector2(1240, 110);
            capRt.anchoredPosition = new Vector2(-20, -285);
            var shadow = capGo.AddComponent<Shadow>();
            shadow.effectColor = new Color(0, 0, 0, 0.9f);
            shadow.effectDistance = new Vector2(2, -2);
            var voiceComp = camGo.GetComponent<VoiceClient>();
            if (voiceComp != null) voiceComp.caption = caption;
            string gate = "";
            try { gate = File.ReadAllText(@"D:\你的数据目录\gate_token.txt").Trim(); } catch { }
            if (voiceComp != null)
                voiceComp.wsUrl = "ws://172.16.1.101:8003/ws?sid=pico&t=" + gate;
            if (client != null)
                client.url = "http://172.16.1.101:8014/panel.mjpg?t=" + gate;
            var camVision = camGo.GetComponent<CameraVision>();
            if (camVision != null)
                camVision.endpoint = "http://172.16.1.101:8003/api/pico_look?t=" + gate;

            var statGo = new GameObject("Status");
            statGo.transform.SetParent(canvasGo.transform, false);
            var status = statGo.AddComponent<Text>();
            status.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            status.fontSize = 16;
            status.color = new Color(0.55f, 0.65f, 0.75f);
            status.alignment = TextAnchor.UpperCenter;
            status.text = "连接中…";
            var statRt = statGo.GetComponent<RectTransform>();
            statRt.sizeDelta = new Vector2(620, 28);
            statRt.anchoredPosition = new Vector2(0, 150);
            if (client != null) client.status = status;
            if (voiceComp != null) voiceComp.status = status;

            UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
        }

        static void BuildNativeScene()
        {
            Directory.CreateDirectory("Assets/Scenes");
            var scene = UnityEditor.SceneManagement.EditorSceneManager.NewScene(
                UnityEditor.SceneManagement.NewSceneSetup.EmptyScene,
                UnityEditor.SceneManagement.NewSceneMode.Single);

            var xrRoot = new GameObject("XR Origin");
            var camOffset = new GameObject("Camera Offset");
            camOffset.transform.SetParent(xrRoot.transform, false);

            var camGo = new GameObject("Main Camera");
            camGo.transform.SetParent(camOffset.transform, false);
            camGo.transform.localPosition = Vector3.zero;
            camGo.transform.localRotation = Quaternion.identity;
            camGo.tag = "MainCamera";
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0, 0, 0, 0);
            cam.nearClipPlane = 0.05f;
            cam.farClipPlane = 100f;
            camGo.AddComponent<AudioListener>();
            camGo.AddComponent<PXR_Manager>();
            camGo.AddComponent<Passthrough>();
            var voice = camGo.AddComponent<VoiceClient>();
            camGo.AddComponent<CameraProbe>();
            var vision = camGo.AddComponent<CameraVision>();
            camGo.AddComponent<DebugCapture>();

            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Live2D/Models/companion/companion.prefab");
            if (prefab == null) throw new System.Exception("Live2D prefab not found");
            var model = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            model.transform.SetParent(camGo.transform, false);
            model.transform.localPosition = new Vector3(0.78f, 0.12f, 1.30f);
            model.transform.localRotation = Quaternion.Euler(0, 180, 0);
            model.transform.localScale = Vector3.one * 0.5f;
            var fitter = model.AddComponent<NativeModelFitter>();
            fitter.target = new Vector3(0.78f, 0.12f, 1.30f);
            fitter.targetHeight = 0.76f;
            model.AddComponent<ArchSort>();
            model.AddComponent<Live2DIdle>();

            var magnifier = camGo.AddComponent<CameraMagnifier>();
            magnifier.vision = vision;
            magnifier.autoOpenForTest = false;
            var holo = camGo.AddComponent<HoloSphereController>();
            holo.magnifier = magnifier;

            // 不再自建射线，交给官方 HandRight 的 DefaultRay

            var handPrefab = AssetDatabase.LoadAssetAtPath<GameObject>(
                "Packages/com.unity.xr.picoxr/Assets/Resources/Prefabs/HandRight.prefab");
            if (handPrefab != null)
            {
                var handGo = (GameObject)PrefabUtility.InstantiatePrefab(handPrefab);
                handGo.name = "OfficialHandRight";
                handGo.transform.SetParent(camOffset.transform, false);
                handGo.transform.localPosition = Vector3.zero;
                handGo.transform.localRotation = Quaternion.identity;
                handGo.transform.localScale = Vector3.one;
                foreach (var r in handGo.GetComponentsInChildren<Renderer>(true)) r.enabled = false;
            }

            var capGo = new GameObject("SubtitleCanvas");
            capGo.transform.SetParent(camGo.transform, false);
            capGo.transform.localPosition = new Vector3(-0.12f, -0.32f, 1.0f);
            capGo.transform.localRotation = Quaternion.identity;
            capGo.transform.localScale = Vector3.one * 0.0006f;
            var canvas = capGo.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            capGo.GetComponent<RectTransform>().sizeDelta = new Vector2(700, 180);
            capGo.AddComponent<CanvasScaler>();
            capGo.AddComponent<GraphicRaycaster>();
            var t = new GameObject("Text");
            t.transform.SetParent(capGo.transform, false);
            var caption = t.AddComponent<Text>();
            caption.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            caption.fontSize = 30;
            caption.color = new Color(0.86f, 0.97f, 1f);
            caption.alignment = TextAnchor.LowerLeft;
            caption.horizontalOverflow = HorizontalWrapMode.Wrap;
            t.GetComponent<RectTransform>().sizeDelta = new Vector2(700, 180);
            voice.caption = caption;

            string gate = "";
            try { gate = File.ReadAllText(@"D:\你的数据目录\gate_token.txt").Trim(); } catch { }
            voice.wsUrl = "ws://172.16.1.101:8003/ws?sid=pico&t=" + gate;
            vision.endpoint = "http://172.16.1.101:8003/api/pico_look?t=" + gate;
            vision.interval = 30f;

            UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
        }

        static void BuildApk()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(ApkPath));
            var options = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = ApkPath,
                target = BuildTarget.Android,
                options = BuildOptions.None,
            };
            BuildReport report = BuildPipeline.BuildPlayer(options);
            Debug.Log($"BUILD RESULT: {report.summary.result} -> {ApkPath}");
            if (report.summary.result != BuildResult.Succeeded)
            {
                throw new System.Exception("Build failed: " + report.summary.result);
            }
        }
    }

    /// <summary>
    /// 允许 http:// 明文（局域网面板流），Android 9+ 默认禁止。
    /// </summary>
    public class CleartextManifest : IPostGenerateGradleAndroidProject
    {
        public int callbackOrder => 1;

        public void OnPostGenerateGradleAndroidProject(string path)
        {
            string manifest = Path.Combine(path, "src/main/AndroidManifest.xml");
            if (!File.Exists(manifest)) return;
            var doc = new XmlDocument();
            doc.Load(manifest);
            var app = doc.SelectSingleNode("/manifest/application") as XmlElement;
            if (app == null) return;
            app.SetAttribute("usesCleartextTraffic", "http://schemas.android.com/apk/res/android", "true");
            var root = doc.SelectSingleNode("/manifest") as XmlElement;
            if (root != null)
            {
                var required = new[] { "android.permission.RECORD_AUDIO", "android.permission.CAMERA" };
                foreach (var perm in required)
                {
                    bool has = false;
                    foreach (XmlElement p in root.SelectNodes("uses-permission"))
                    {
                        if (p.GetAttribute("name", "http://schemas.android.com/apk/res/android") == perm) has = true;
                    }
                    if (!has)
                    {
                        var p = doc.CreateElement("uses-permission");
                        p.SetAttribute("name", "http://schemas.android.com/apk/res/android", perm);
                        root.AppendChild(p);
                    }
                }
            }
            doc.Save(manifest);
        }
    }
}
