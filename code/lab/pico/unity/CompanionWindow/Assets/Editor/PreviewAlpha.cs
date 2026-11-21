using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.UI;

public static class PreviewAlpha
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

        var canvasGo = new GameObject("WindowCanvas");
        canvasGo.transform.position = new Vector3(0.35f, 1.6f, 1.2f);
        var canvas = canvasGo.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.WorldSpace;
        var rt = canvasGo.GetComponent<RectTransform>();
        rt.sizeDelta = new Vector2(1008, 921);
        canvasGo.transform.localScale = Vector3.one * 0.00055f;
        canvasGo.AddComponent<CanvasScaler>();
        canvasGo.AddComponent<GraphicRaycaster>();

        var panel = new GameObject("Panel");
        panel.transform.SetParent(canvasGo.transform, false);
        var raw = panel.AddComponent<RawImage>();
        raw.color = Color.white;
        panel.GetComponent<RectTransform>().sizeDelta = new Vector2(1008, 921);

        var client = panel.AddComponent<Companion.AlphaClient>();
        client.target = raw;
        client.url = "http://127.0.0.1:8003/panel/frame.png";

        EditorSceneManager.SaveScene(scene, "Assets/Scenes/PreviewAlpha.unity");
        var opts = new BuildPlayerOptions
        {
            scenes = new[] { "Assets/Scenes/PreviewAlpha.unity" },
            locationPathName = @"D:\dev\companion_alpha_win\companion.exe",
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.None,
        };
        var report = BuildPipeline.BuildPlayer(opts);
        Debug.Log("PreviewAlpha: " + report.summary.result);
    }
}
