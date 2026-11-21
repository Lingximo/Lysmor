using UnityEditor;
using UnityEngine;
using UnityEditor.XR.Management;
using Unity.XR.OpenXR.Features.PICOSupport;
using Unity.XR.PXR;
using UnityEngine.XR.Management;
using UnityEngine.XR.OpenXR;
using UnityEngine.XR.OpenXR.Features;

namespace Companion.Editor
{
    public static class OpenXRSetup
    {
        public static void Setup()
        {
            EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Android, BuildTarget.Android);
            var perType = typeof(XRGeneralSettingsPerBuildTarget);
            var getOrCreate = perType.GetMethod("GetOrCreate", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic);
            var per = getOrCreate != null ? getOrCreate.Invoke(null, null) as XRGeneralSettingsPerBuildTarget : null;
            if (per != null)
            {
                per.CreateDefaultManagerSettingsForBuildTarget(BuildTargetGroup.Android);
                EditorUtility.SetDirty(per);
                AssetDatabase.SaveAssets();
            }
            var general = XRGeneralSettingsPerBuildTarget.XRGeneralSettingsForBuildTarget(BuildTargetGroup.Android);
            var loader = AssetDatabase.LoadAssetAtPath<XRLoader>("Packages/com.unity.xr.openxr/Runtime/OpenXRLoader.asset");
            if (loader == null)
            {
                loader = ScriptableObject.CreateInstance<OpenXRLoader>();
                System.IO.Directory.CreateDirectory("Assets/XR");
                AssetDatabase.CreateAsset(loader, "Assets/XR/OpenXRLoader.asset");
                AssetDatabase.SaveAssets();
            }
            if (general != null && general.Manager != null && loader != null)
            {
                general.Manager.TryAddLoader(loader);
                var so = new SerializedObject(general.Manager);
                var loaders = so.FindProperty("m_Loaders");
                if (loaders != null)
                {
                    loaders.arraySize = 1;
                    loaders.GetArrayElementAtIndex(0).objectReferenceValue = loader;
                }
                var autoLoad = so.FindProperty("m_AutomaticLoading");
                if (autoLoad != null) autoLoad.boolValue = true;
                var autoRun = so.FindProperty("m_AutomaticRunning");
                if (autoRun != null) autoRun.boolValue = true;
                so.ApplyModifiedProperties();
                EditorUtility.SetDirty(general.Manager);
                AssetDatabase.SaveAssets();
            }

            // 创建并注册 OpenXR Package Settings（编辑器内部类，反射调用官方创建入口）
            var psType = System.Type.GetType("UnityEditor.XR.OpenXR.OpenXRPackageSettings, Unity.XR.OpenXR.Editor");
            if (psType != null)
            {
                var m = psType.GetMethod("GetOrCreateInstance", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static);
                if (m != null) m.Invoke(null, null);
                Debug.Log("OpenXRSetup: package settings type=" + psType.FullName);
            }
            AssetDatabase.Refresh();

            var settings = OpenXRSettings.ActiveBuildTargetInstance;
            if (settings != null)
            {
                var f = settings.GetFeature<PICOFeature>();
                if (f == null)
                {
                    f = ScriptableObject.CreateInstance<PICOFeature>();
                    var field = typeof(OpenXRSettings).GetField("features", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    if (field != null)
                    {
                        var arr = field.GetValue(settings) as OpenXRFeature[];
                        if (arr == null) arr = new OpenXRFeature[0];
                        var list = new System.Collections.Generic.List<OpenXRFeature>(arr) { f };
                        field.SetValue(settings, list.ToArray());
                    }
                }
                if (f != null) { f.enabled = true; EditorUtility.SetDirty(settings); }

                var hf = settings.GetFeature<UnityEngine.XR.Hands.OpenXR.HandTracking>();
                if (hf == null)
                {
                    hf = ScriptableObject.CreateInstance<UnityEngine.XR.Hands.OpenXR.HandTracking>();
                    var fieldH = typeof(OpenXRSettings).GetField("features", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    if (fieldH != null)
                    {
                        var arrH = fieldH.GetValue(settings) as OpenXRFeature[];
                        if (arrH == null) arrH = new OpenXRFeature[0];
                        var listH = new System.Collections.Generic.List<OpenXRFeature>(arrH) { hf };
                        fieldH.SetValue(settings, listH.ToArray());
                    }
                }
                if (hf != null) { hf.enabled = true; EditorUtility.SetDirty(settings); }

                var cf = settings.GetFeature<UnityEngine.XR.OpenXR.Features.Interactions.PICO4UltraControllerProfile>();
                if (cf == null)
                {
                    cf = ScriptableObject.CreateInstance<UnityEngine.XR.OpenXR.Features.Interactions.PICO4UltraControllerProfile>();
                    var fieldC = typeof(OpenXRSettings).GetField("features", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    if (fieldC != null)
                    {
                        var arrC = fieldC.GetValue(settings) as OpenXRFeature[];
                        if (arrC == null) arrC = new OpenXRFeature[0];
                        var listC = new System.Collections.Generic.List<OpenXRFeature>(arrC) { cf };
                        fieldC.SetValue(settings, listC.ToArray());
                    }
                }
                if (cf != null) { cf.enabled = true; EditorUtility.SetDirty(settings); }
                var camf = settings.GetFeature<PicoCameraExtensionProbe>();
                if (camf == null)
                {
                    camf = ScriptableObject.CreateInstance<PicoCameraExtensionProbe>();
                    var fieldCam = typeof(OpenXRSettings).GetField("features", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    if (fieldCam != null)
                    {
                        var arrCam = fieldCam.GetValue(settings) as OpenXRFeature[];
                        if (arrCam == null) arrCam = new OpenXRFeature[0];
                        var listCam = new System.Collections.Generic.List<OpenXRFeature>(arrCam) { camf };
                        fieldCam.SetValue(settings, listCam.ToArray());
                    }
                }
                if (camf != null)
                {
                    var extField = typeof(OpenXRFeature).GetField("openxrExtensionStrings",
                        System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    if (extField != null)
                        extField.SetValue(camf, "XR_PICO_camera_image XR_PICO_external_camera");
                    camf.enabled = true;
                    EditorUtility.SetDirty(settings);
                }
                Debug.Log("OpenXRSetup: cameraProbe=" + (camf != null) + " enabled=" + (camf != null && camf.enabled));
                var pf = settings.GetFeature<PassthroughFeature>();
                if (pf == null)
                {
                    pf = ScriptableObject.CreateInstance<PassthroughFeature>();
                    var fieldP = typeof(OpenXRSettings).GetField("features", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
                    if (fieldP != null)
                    {
                        var arrP = fieldP.GetValue(settings) as OpenXRFeature[];
                        if (arrP == null) arrP = new OpenXRFeature[0];
                        var listP = new System.Collections.Generic.List<OpenXRFeature>(arrP) { pf };
                        fieldP.SetValue(settings, listP.ToArray());
                    }
                }
                if (pf != null) { pf.enabled = true; EditorUtility.SetDirty(settings); }
                Debug.Log("OpenXRSetup: passthrough=" + (pf != null));

                var cfg = PICOProjectSetting.GetProjectConfig();
                cfg.isHandTracking = true;
                cfg.handTrackingSupportType = HandTrackingSupport.ControllersAndHands;
                EditorUtility.SetDirty(cfg);
                AssetDatabase.SaveAssets();
                Debug.Log("OpenXRSetup: handTracking=" + cfg.isHandTracking);
                AssetDatabase.SaveAssets();
                Debug.Log("OpenXRSetup: feature=" + (f != null) + " loader=" + (loader != null));
            }
            else Debug.LogWarning("OpenXRSetup: settings null");
        }
    }
}
