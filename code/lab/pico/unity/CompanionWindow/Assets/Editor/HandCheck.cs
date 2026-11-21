using UnityEditor;
using UnityEngine;

public static class HandCheck
{
    public static void Run()
    {
        var path = "Packages/com.unity.xr.picoxr/Assets/Resources/Prefabs/HandRight.prefab";
        var p = AssetDatabase.LoadAssetAtPath<GameObject>(path);
        Debug.Log("HandCheck prefab=" + (p != null) + " path=" + path);
        if (p == null) return;
        Dump(p.transform, 0);
        var mono = p.GetComponentsInChildren<MonoBehaviour>(true);
        foreach (var m in mono)
        {
            if (m == null) continue;
            Debug.Log("HandCheck comp " + m.GetType().FullName + " on " + m.name);
        }
    }

    static void Dump(Transform t, int depth)
    {
        if (depth > 4) return;
        Debug.Log("HandCheck node " + new string(' ', depth * 2) + t.name + " active=" + t.gameObject.activeSelf);
        foreach (Transform c in t) Dump(c, depth + 1);
    }
}
