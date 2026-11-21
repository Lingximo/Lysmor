using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR.Management;
using UnityEngine.XR.OpenXR;
using Unity.XR.OpenXR.Features.PICOSupport;

namespace Companion.Editor
{
    public static class OpenXRBuild
    {
        const string ScenePath = "Assets/Scenes/OpenXRProbe.unity";
        const string ApkPath = @"D:\dev\companion-openxr.apk";

        public static void Build()
        {
            var general = XRGeneralSettingsPerBuildTarget.XRGeneralSettingsForBuildTarget(BuildTargetGroup.Android);
            var loader = AssetDatabase.LoadAssetAtPath<XRLoader>("Packages/com.unity.xr.openxr/Runtime/OpenXRLoader.asset");
            if (general != null && general.Manager != null && loader != null)
                general.Manager.TryAddLoader(loader);

            var settings = OpenXRSettings.GetSettingsForBuildTargetGroup(BuildTargetGroup.Android);
            if (settings != null)
            {
                var f = settings.GetFeature<PICOFeature>();
                if (f != null) { f.enabled = true; EditorUtility.SetDirty(settings); }
            }

            PlayerSettings.colorSpace = ColorSpace.Linear;
            PlayerSettings.companyName = "Companion";
            PlayerSettings.productName = "CompanionOpenXR";
            PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Android, "com.companion.openxr");
            PlayerSettings.SetScriptingBackend(NamedBuildTarget.Android, ScriptingImplementation.IL2CPP);
            var psAssets = AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/ProjectSettings.asset");
            if (psAssets != null && psAssets.Length > 0)
            {
                var pso = new SerializedObject(psAssets[0]);
                var p = pso.FindProperty("activeInputHandler");
                if (p != null) { p.intValue = 1; pso.ApplyModifiedProperties(); }
            }
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            PlayerSettings.Android.forceInternetPermission = true;
            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel29;
            PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevel33;

            Directory.CreateDirectory("Assets/Scenes");
            var scene = UnityEditor.SceneManagement.EditorSceneManager.NewScene(
                UnityEditor.SceneManagement.NewSceneSetup.EmptyScene,
                UnityEditor.SceneManagement.NewSceneMode.Single);
            var camGo = new GameObject("Main Camera");
            camGo.tag = "MainCamera";
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0f, 0f, 0f, 0f);
            camGo.AddComponent<AudioListener>();
            camGo.AddComponent<OpenXRHandProbe>();
            camGo.AddComponent<OpenXRHandRay>();
            camGo.AddComponent<PassthroughEnabler>();
            camGo.AddComponent<XRHeadDriver>();
            camGo.AddComponent<WebCamProbe>();
            camGo.AddComponent<PxrCameraProbe>();

            var voice = camGo.AddComponent<VoiceClient>();
            var speaker = camGo.AddComponent<AudioSource>();
            voice.speaker = speaker;
            string gate = "";
            try { gate = File.ReadAllText(@"D:\你的数据目录\gate_token.txt").Trim(); } catch { }
            voice.wsUrl = "ws://YOUR-PC.local:8003/ws?sid=pico&t=" + gate;

            var capGo = new GameObject("SubtitleCanvas");
            capGo.transform.SetParent(camGo.transform, false);
            capGo.transform.localPosition = new Vector3(-0.12f, -0.24f, 1.0f);
            capGo.transform.localRotation = Quaternion.identity;
            capGo.transform.localScale = Vector3.one * 0.0006f;
            var capCanvas = capGo.AddComponent<Canvas>();
            capCanvas.renderMode = RenderMode.WorldSpace;
            capGo.GetComponent<RectTransform>().sizeDelta = new Vector2(700, 180);
            capGo.AddComponent<CanvasScaler>();
            capGo.AddComponent<GraphicRaycaster>();
            var capTextGo = new GameObject("Text");
            capTextGo.transform.SetParent(capGo.transform, false);
            var caption = capTextGo.AddComponent<Text>();
            caption.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            caption.fontSize = 30;
            caption.color = new Color(0.86f, 0.97f, 1f);
            caption.alignment = TextAnchor.LowerLeft;
            caption.horizontalOverflow = HorizontalWrapMode.Wrap;
            capTextGo.GetComponent<RectTransform>().sizeDelta = new Vector2(700, 180);
            voice.caption = caption;
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Live2D/Models/companion/companion.prefab");
            if (prefab != null)
            {
                var model = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
                model.transform.SetParent(camGo.transform, false);
                model.transform.localPosition = new Vector3(0.45f, -0.05f, 1.30f);
                model.transform.localRotation = Quaternion.Euler(0, 180, 0);
                model.transform.localScale = Vector3.one * 0.5f;
                var fitter = model.AddComponent<NativeModelFitter>();
                fitter.target = new Vector3(0.45f, -0.05f, 1.30f);
                fitter.targetHeight = 0.76f;
                model.AddComponent<ArchSort>();
                model.AddComponent<Live2DIdle>();
            }
            UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };

            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = ApkPath,
                target = BuildTarget.Android,
                options = BuildOptions.None,
            });
            Debug.Log("OPENXR BUILD: " + report.summary.result);
            if (report.summary.result != BuildResult.Succeeded)
                throw new System.Exception("OpenXR build failed: " + report.summary.result);
        }
    }
}
