using System.Collections;
using UnityEngine;

namespace Companion
{
    /// <summary>
    /// Cubism 的 Renderer.bounds 在编辑期是空的，运行时才由动态网格算出来。
    /// 这里在第一帧后按真实包围盒把模型缩到 1 米高，并放到镜头右前方。
    /// </summary>
    public class NativeModelFitter : MonoBehaviour
    {
        public Vector3 target = new Vector3(0.38f, -0.02f, 1.30f);
        public float targetHeight = 1.0f;
        public bool faceCamera = false;

        IEnumerator Start()
        {
            // Cubism 的网格/包围盒不是第一帧就有，等它真的长出来再定位
            for (int attempt = 0; attempt < 60; attempt++)
            {
                yield return null;
                var rs = GetComponentsInChildren<Renderer>();
                if (rs.Length == 0)
                {
                    if (attempt % 10 == 0) Debug.Log("NativeModelFitter waiting renderers");
                    continue;
                }
                var b = rs[0].bounds;
                for (int i = 1; i < rs.Length; i++) b.Encapsulate(rs[i].bounds);
                if (b.size.y < 0.05f)
                {
                    if (attempt % 10 == 0) Debug.Log("NativeModelFitter waiting bounds=" + b.size);
                    continue;
                }

                float s = targetHeight / b.size.y;
                transform.localScale *= s;
                yield return null;

                b = rs[0].bounds;
                for (int i = 1; i < rs.Length; i++) b.Encapsulate(rs[i].bounds);
                var targetWorld = transform.parent != null ? transform.parent.TransformPoint(target) : target;
                transform.position += targetWorld - b.center;
                Debug.Log($"NativeModelFitter ok renderers={rs.Length} bounds={b.size} scale={s} pos={transform.position}");
                yield break;
            }
            Debug.LogWarning("NativeModelFitter gave up");
        }
    }
}
