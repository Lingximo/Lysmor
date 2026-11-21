using System.Collections.Generic;
using System.Collections;
using UnityEngine;
using Live2D.Cubism.Core;

namespace Companion
{
    /// <summary>
    /// 用原 Web 运行时导出的 drawable renderOrder 直接设置 Unity 的 sortingOrder。
    /// 不再依赖 SDK 导入器自己推顺序。
    /// </summary>
    public class ArchSort : MonoBehaviour
    {
        [System.Serializable] public class Item { public string id; public int order; }
        [System.Serializable] public class Data { public int count; public List<Item> drawables; }

        IEnumerator Start()
        {
            var ta = Resources.Load<TextAsset>("live2d_arch");
            if (ta == null) { Debug.LogWarning("ArchSort: json missing"); yield break; }
            var data = JsonUtility.FromJson<Data>(ta.text);
            if (data == null || data.drawables == null) { Debug.LogWarning("ArchSort: json bad"); yield break; }

            yield return null;
            yield return null;

            var model = GetComponent<CubismModel>();
            if (model == null) model = GetComponentInChildren<CubismModel>();
            if (model == null) { Debug.LogWarning("ArchSort: model missing"); yield break; }

            var map = new Dictionary<string, int>();
            foreach (var it in data.drawables) map[it.id] = it.order;

            int applied = 0;
            foreach (var d in model.Drawables)
            {
                var mr = d.GetComponent<MeshRenderer>();
                if (mr == null) continue;
                if (map.TryGetValue(d.Id, out int order))
                {
                    mr.sortingOrder = order;
                    applied++;
                }
            }
            Debug.Log($"ArchSort applied={applied}/{model.Drawables.Length}");
        }
    }
}
