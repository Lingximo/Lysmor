using UnityEngine;

namespace Companion
{
    /// <summary>
    /// GLB 没有动画，用骨骼做程序化待机：呼吸、轻微摆头、身体晃。
    /// </summary>
    public class Model3DIdle : MonoBehaviour
    {
        Transform head, chest, hips, spine;
        Quaternion headBase, chestBase, hipsBase, spineBase;
        float t0;

        Transform FindDeep(string name)
        {
            foreach (var t in GetComponentsInChildren<Transform>())
                if (t.name == name) return t;
            return null;
        }

        void Start()
        {
            head = FindDeep("J_Bip_C_Head");
            chest = FindDeep("J_Bip_C_Chest");
            hips = FindDeep("J_Bip_C_Hips");
            spine = FindDeep("J_Bip_C_Spine");
            if (head != null) headBase = head.localRotation;
            if (chest != null) chestBase = chest.localRotation;
            if (hips != null) hipsBase = hips.localRotation;
            if (spine != null) spineBase = spine.localRotation;
            t0 = Random.Range(0f, 4f);
        }

        void LateUpdate()
        {
            float t = Time.time + t0;
            if (head != null)
                head.localRotation = headBase * Quaternion.Euler(
                    2.5f * Mathf.Sin(t * 0.63f),
                    4.5f * Mathf.Sin(t * 0.47f),
                    2.0f * Mathf.Sin(t * 0.39f + 0.8f));
            if (chest != null)
                chest.localRotation = chestBase * Quaternion.Euler(
                    1.2f * Mathf.Sin(t * 0.9f),
                    0.8f * Mathf.Sin(t * 0.6f),
                    0.8f * Mathf.Sin(t * 0.5f));
            if (spine != null)
                spine.localRotation = spineBase * Quaternion.Euler(
                    0.9f * Mathf.Sin(t * 0.8f + 0.5f), 0f, 0f);
            if (hips != null)
                hips.localRotation = hipsBase * Quaternion.Euler(0f, 0f, 0.8f * Mathf.Sin(t * 0.45f));
        }
    }
}
