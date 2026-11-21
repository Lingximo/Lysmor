using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class Preview3D
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

        var lightGo = new GameObject("Key Light");
        var light = lightGo.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 1.2f;
        lightGo.transform.rotation = Quaternion.Euler(35f, 155f, 0f);

        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Models/girl.glb");
        Debug.Log("Preview3D prefab=" + (prefab != null));
        var model = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
        model.transform.position = new Vector3(0.38f, 1.2f, 1.4f);
        model.transform.rotation = Quaternion.Euler(0f, 180f, 0f);
        model.transform.localScale = Vector3.one;

        var rs = model.GetComponentsInChildren<Renderer>();
        if (rs.Length > 0)
        {
            var b = rs[0].bounds;
            for (int i = 1; i < rs.Length; i++) b.Encapsulate(rs[i].bounds);
            Debug.Log("Preview3D bounds=" + b.size + " center=" + b.center);
            float s = 1.45f / Mathf.Max(0.1f, b.size.y);
            model.transform.localScale = Vector3.one * s;
            Debug.Log("Preview3D scale=" + s);
        }

        EditorSceneManager.SaveScene(scene, "Assets/Scenes/Preview3D.unity");
        var opts = new BuildPlayerOptions
        {
            scenes = new[] { "Assets/Scenes/Preview3D.unity" },
            locationPathName = @"D:\dev\companion_3d\companion.exe",
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.None,
        };
        var report = BuildPipeline.BuildPlayer(opts);
        Debug.Log("Preview3D build: " + report.summary.result);
    }
}
