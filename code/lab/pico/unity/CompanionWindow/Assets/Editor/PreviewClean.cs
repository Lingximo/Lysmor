using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Live2D.Cubism.Rendering;

public static class PreviewClean
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

        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Live2D/Models/companion/companion.prefab");
        var model = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
        model.transform.position = new Vector3(0.38f, 1.6f, 1.30f);
        model.transform.rotation = Quaternion.Euler(0f, 180f, 0f);
        model.transform.localScale = Vector3.one * 0.5f;
        model.AddComponent<Companion.ArchSort>();

        var rc = model.GetComponentInChildren<CubismRenderController>();
        if (rc != null) rc.CameraToFace = null;


        EditorSceneManager.SaveScene(scene, "Assets/Scenes/PreviewFull.unity");
        var opts = new BuildPlayerOptions
        {
            scenes = new[] { "Assets/Scenes/PreviewFull.unity" },
            locationPathName = @"D:\dev\companion_full\companion.exe",
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.None,
        };
        var report = BuildPipeline.BuildPlayer(opts);
        Debug.Log("Clean preview: " + report.summary.result);
    }
}
