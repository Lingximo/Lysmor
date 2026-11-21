using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.UI;
using Live2D.Cubism.Core;
using Live2D.Cubism.Framework;
using Live2D.Cubism.Rendering;

public static class PreviewBuild
{
    public static void Build()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

        var camGo = new GameObject("Main Camera");
        camGo.tag = "MainCamera";
        var cam = camGo.AddComponent<Camera>();
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = new Color(0.12f, 0.14f, 0.18f);
        cam.nearClipPlane = 0.05f;
        cam.farClipPlane = 100f;
        camGo.transform.position = new Vector3(0f, 1.6f, 0f);

        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(
            "Assets/Live2D/Models/companion/companion.prefab");
        var model = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
        model.transform.SetParent(camGo.transform, false);
        model.transform.localPosition = new Vector3(0.38f, 0f, 1.30f);
        model.transform.localRotation = Quaternion.Euler(0f, 180f, 0f);
        model.transform.localScale = Vector3.one * 0.5f;
        model.AddComponent<Companion.NativeModelFitter>();
        model.AddComponent<CubismUpdateController>();
        var rc = model.GetComponent<CubismRenderController>();
        if (rc != null) { rc.SortingMode = CubismSortingMode.BackToFrontOrder; rc.SortingOrder = 0; }
        model.AddComponent<Companion.Live2DIdle>();

        var cap = new GameObject("SubtitleCanvas");
        cap.transform.SetParent(camGo.transform, false);
        cap.transform.localPosition = new Vector3(-0.40f, -0.24f, 1.0f);
        cap.transform.localRotation = Quaternion.identity;
        cap.transform.localScale = Vector3.one * 0.0006f;
        var canvas = cap.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.WorldSpace;
        cap.GetComponent<RectTransform>().sizeDelta = new Vector2(700, 180);
        cap.AddComponent<CanvasScaler>();

        var t = new GameObject("Subtitle");
        t.transform.SetParent(cap.transform, false);
        var text = t.AddComponent<Text>();
        text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        text.fontSize = 34;
        text.color = Color.white;
        text.alignment = TextAnchor.LowerLeft;
        text.text = "测试字幕 ABC 123 左";
        t.GetComponent<RectTransform>().sizeDelta = new Vector2(700, 180);

        EditorSceneManager.SaveScene(scene, "Assets/Scenes/Preview.unity");
        var opts = new BuildPlayerOptions
        {
            scenes = new[] { "Assets/Scenes/Preview.unity" },
            locationPathName = @"D:\dev\companion_preview2\companion.exe",
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.None,
        };
        var report = BuildPipeline.BuildPlayer(opts);
        Debug.Log("Preview build: " + report.summary.result + " size=" + report.summary.totalSize);
    }
}
