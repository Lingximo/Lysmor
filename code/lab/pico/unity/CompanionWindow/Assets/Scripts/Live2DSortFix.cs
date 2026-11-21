using UnityEngine;
using Live2D.Cubism.Core;

namespace Companion
{
    /// <summary>
    /// 保险丝：直接按 drawable 顺序给每个 MeshRenderer 排 sortingOrder。
    /// 不依赖 SDK 的排序模式，先保证脸/头发/尾巴不再乱压。
    /// </summary>
    public class Live2DSortFix : MonoBehaviour
    {
        CubismModel model;
        MeshRenderer[] renderers;

        void LateUpdate()
        {
            if (model == null)
            {
                model = GetComponent<CubismModel>();
                if (model == null) model = GetComponentInChildren<CubismModel>();
                if (model == null) return;
            }
            if (renderers == null || renderers.Length != model.Drawables.Length)
            {
                renderers = new MeshRenderer[model.Drawables.Length];
                for (int i = 0; i < renderers.Length; i++)
                    renderers[i] = model.Drawables[i].GetComponent<MeshRenderer>();
            }
            for (int i = 0; i < renderers.Length; i++)
            {
                if (renderers[i] != null && renderers[i].sortingOrder != i)
                    renderers[i].sortingOrder = i;
            }
        }
    }
}
