using System.Collections;
using UnityEngine;

namespace Companion
{
    /// <summary>
    /// 3D 模型放进相机后：按包围盒缩到目标身高，放到右前方。
    /// </summary>
    public class Model3DFitter : MonoBehaviour
    {
        public Vector3 target = new Vector3(0.45f, -0.35f, 1.35f);
        public float targetHeight = 1.25f;
        public bool faceCamera = false;

        IEnumerator Start()
        {
            yield return null;
            yield return null;
            var rs = GetComponentsInChildren<Renderer>();
            if (rs.Length == 0) yield break;
            var b = rs[0].bounds;
            for (int i = 1; i < rs.Length; i++) b.Encapsulate(rs[i].bounds);
            if (b.size.y < 0.05f) yield break;

            float s = targetHeight / b.size.y;
            transform.localScale *= s;
            yield return null;

            b = rs[0].bounds;
            for (int i = 1; i < rs.Length; i++) b.Encapsulate(rs[i].bounds);
            var targetWorld = transform.parent != null ? transform.parent.TransformPoint(target) : target;
            transform.position += targetWorld - b.center;

            if (faceCamera && Camera.main != null)
            {
                var dir = Camera.main.transform.position - transform.position;
                transform.rotation = Quaternion.LookRotation(-dir, Vector3.up);
            }
            Debug.Log($"Model3DFitter ok h={b.size.y} scale={s} pos={transform.position}");
        }
    }
}
