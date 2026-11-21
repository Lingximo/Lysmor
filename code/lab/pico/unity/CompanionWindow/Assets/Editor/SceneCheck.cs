using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Live2D.Cubism.Core;

public static class SceneCheck
{
    public static void Check()
    {
        var scene = EditorSceneManager.OpenScene("Assets/Scenes/Main.unity");
        var models = Object.FindObjectsOfType<CubismModel>();
        Debug.Log("SceneCheck models=" + models.Length);
        foreach (var m in models)
        {
            var rs = m.GetComponentsInChildren<Renderer>();
            var b = new Bounds(m.transform.position, Vector3.zero);
            bool first = true;
            foreach (var r in rs)
            {
                if (first) { b = r.bounds; first = false; }
                else b.Encapsulate(r.bounds);
            }
            Debug.Log($"SceneCheck {m.name} renderers={rs.Length} pos={m.transform.position} " +
                      $"boundsCenter={b.center} size={b.size}");
        }
        var cam = Camera.main;
        Debug.Log("SceneCheck cam=" + (cam != null ? cam.transform.position.ToString() : "none"));
    }
}
