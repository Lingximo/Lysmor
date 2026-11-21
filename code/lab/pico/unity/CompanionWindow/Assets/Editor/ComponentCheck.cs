using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Live2D.Cubism.Core;
using Live2D.Cubism.Rendering.Masking;

public static class ComponentCheck
{
    public static void Run()
    {
        EditorSceneManager.OpenScene("Assets/Scenes/Preview.unity");
        var m = Object.FindObjectOfType<CubismModel>();
        Debug.Log("ComponentCheck model=" + (m != null));
        if (m == null) return;
        foreach (var c in m.GetComponents<Component>())
            Debug.Log("root: " + c.GetType().FullName);
        foreach (var c in m.GetComponentsInChildren<CubismMaskController>(true))
            Debug.Log("mask controller: " + c.GetType().FullName + " enabled=" + c.enabled);
        var rc = m.GetComponentInChildren<Live2D.Cubism.Rendering.CubismRenderController>();
        Debug.Log("render controller=" + (rc != null) + " sorting=" + (rc != null ? rc.SortingMode.ToString() : ""));
    }
}
