using System.Collections.Generic;
using UnityEngine;
using Live2D.Cubism.Core;
using Live2D.Cubism.Framework;

namespace Companion
{
    /// <summary>
    /// 模型没有自带 motion，这里补一个程序化待机：
    /// 呼吸、轻微摆头、眨眼、说话时嘴动。
    /// </summary>
    public class Live2DIdle : MonoBehaviour
    {
        CubismModel model;
        readonly Dictionary<string, CubismParameter> map = new Dictionary<string, CubismParameter>();
        bool hasBlink;
        float blinkAt;
        float blinkUntil;
        AudioSource speaker;
        readonly float[] samples = new float[256];

        void Start()
        {
            model = GetComponent<CubismModel>();
            if (model == null) model = GetComponentInChildren<CubismModel>();
            if (model == null) return;
            foreach (var p in model.Parameters)
            {
                if (p != null && !map.ContainsKey(p.Id)) map[p.Id] = p;
            }
            hasBlink = GetComponent<CubismEyeBlinkController>() != null ||
                       GetComponentInChildren<CubismEyeBlinkController>() != null;
            speaker = FindObjectOfType<AudioSource>();
            blinkAt = Time.time + Random.Range(2f, 5f);
        }

        void Set(string id, float value)
        {
            if (map.TryGetValue(id, out var p))
                p.Value = Mathf.Clamp(value, p.MinimumValue, p.MaximumValue);
        }

        void LateUpdate()
        {
            if (model == null) return;
            float t = Time.time;

            // 待机：呼吸 + 很慢的摆头
            Set("ParamBreath", 0.5f + 0.5f * Mathf.Sin(t * 1.4f));
            Set("ParamAngleX", 5f * Mathf.Sin(t * 0.55f));
            Set("ParamAngleY", 3f * Mathf.Sin(t * 0.83f + 0.7f));
            Set("ParamAngleZ", 2.2f * Mathf.Sin(t * 0.37f + 1.2f));
            Set("ParamBodyAngleX", 2.5f * Mathf.Sin(t * 0.41f));
            Set("ParamBodyAngleZ", 1.5f * Mathf.Sin(t * 0.29f + 0.4f));

            // 眨眼：每 3~6 秒一次，闭 0.12 秒
            if (!hasBlink)
            {
                if (t > blinkAt && blinkUntil <= 0f)
                {
                    blinkUntil = t + 0.12f;
                    blinkAt = t + Random.Range(3f, 6f);
                }
                float open = (blinkUntil > 0f && t < blinkUntil) ? 0.05f : 1f;
                Set("ParamEyeLOpen", open);
                Set("ParamEyeROpen", open);
            }

            // 说话时嘴动
            float mouth = 0f;
            if (speaker != null && speaker.isPlaying)
            {
                speaker.GetOutputData(samples, 0);
                float sum = 0f;
                for (int i = 0; i < samples.Length; i++) sum += samples[i] * samples[i];
                mouth = Mathf.Clamp01(Mathf.Sqrt(sum / samples.Length) * 14f);
            }
            Set("ParamMouthOpenY", mouth);
        }
    }
}
