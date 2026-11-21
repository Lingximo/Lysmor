using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Live2D.Cubism.Core;
using Live2D.Cubism.Rendering;
using Live2D.Cubism.Rendering.Masking;

public static class CleanCheck
{
    public static void Run()
    {
        EditorSceneManager.OpenScene("Assets/Scenes/PreviewClean.unity");
        var m = Object.FindObjectOfType<CubismModel>();
        Debug.Log("CleanCheck model=" + (m != null));
        if (m == null) return;
        Debug.Log("CleanCheck modelGo=" + m.gameObject.name + " parent=" + (m.transform.parent != null ? m.transform.parent.name : "none"));
        foreach (var c in m.GetComponents<Component>())
            Debug.Log("model component: " + c.GetType().FullName);
        var rc = m.GetComponent<CubismRenderController>();
        Debug.Log("render on model=" + (rc != null));
        if (rc != null)
        {
            Debug.Log("sorting=" + rc.SortingMode + " order=" + rc.SortingOrder + " cameraToFace=" + (rc.CameraToFace != null));
        }
        var mc = m.GetComponent<CubismMaskController>();
        Debug.Log("mask on model=" + (mc != null));
        if (mc != null)
        {
            Debug.Log("mask texture=" + (mc.MaskTexture != null) + " buffers=" + mc.CountOfCommandBuffers);
        }
        var rs = m.GetComponentsInChildren<MeshRenderer>();
        for (int i = 0; i < Mathf.Min(rs.Length, 12); i++)
            Debug.Log($"mesh {i} {rs[i].name} order={rs[i].sortingOrder} mat={rs[i].sharedMaterial?.name} queue={rs[i].sharedMaterial?.renderQueue}");
    }
}
