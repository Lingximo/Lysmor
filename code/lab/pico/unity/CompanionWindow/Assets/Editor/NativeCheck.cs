using UnityEditor;
using UnityEngine;
using Live2D.Cubism.Framework.Json;

public static class NativeCheck
{
    public static void Reimport()
    {
        UnityEditor.AssetDatabase.ImportAsset(
            "Assets/Live2D/Models/companion/companion.model3.json",
            UnityEditor.ImportAssetOptions.ForceUpdate);
        Debug.Log("Reimport done");
    }

    public static void Check()
    {
        var json = CubismModel3Json.LoadAtPath("Assets/Live2D/Models/companion/companion.model3.json");
        Debug.Log("NativeCheck json=" + (json != null));
        if (json == null) return;
        var model = json.ToModel();
        Debug.Log("NativeCheck model=" + (model != null) + " drawables=" +
                  (model != null && model.Drawables != null ? model.Drawables.Length : -1));
    }
}
