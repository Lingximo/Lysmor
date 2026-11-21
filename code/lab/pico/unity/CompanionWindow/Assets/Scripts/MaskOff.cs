using UnityEngine;
using Live2D.Cubism.Rendering;
using Live2D.Cubism.Rendering.Masking;

namespace Companion
{
    /// <summary>试验：关掉 mask，把所有 drawable 用无遮罩 Unlit 材质渲染。</summary>
    public class MaskOff : MonoBehaviour
    {
        void Start()
        {
            var mc = GetComponent<CubismMaskController>();
            if (mc != null) mc.enabled = false;
            var shader = Shader.Find("Live2D Cubism/Unlit");
            if (shader == null) { Debug.LogWarning("MaskOff: shader not found"); return; }
            foreach (var r in GetComponentsInChildren<CubismRenderer>())
            {
                var m = new Material(shader);
                m.mainTexture = r.MainTexture;
                r.Material = m;
            }
        }
    }
}
