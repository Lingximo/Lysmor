using System.Collections;
using System.IO;
using UnityEngine;

namespace Companion
{
    /// <summary>调试：定时把相机画面存成 PNG，方便 adb pull 和网页端对比。</summary>
    public class DebugCapture : MonoBehaviour
    {
        public int width = 1008;
        public int height = 921;
        public float interval = 4f;

        IEnumerator Start()
        {
            yield return new WaitForSeconds(3f);
            while (true)
            {
                Capture();
                yield return new WaitForSeconds(interval);
            }
        }

        void Capture()
        {
            try
            {
                var cam = GetComponent<Camera>();
                if (cam == null) return;
                var rt = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
                var prev = cam.targetTexture;
                cam.targetTexture = rt;
                cam.Render();
                RenderTexture.active = rt;
                var tex = new Texture2D(width, height, TextureFormat.RGBA32, false);
                tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                tex.Apply();
                cam.targetTexture = prev;
                RenderTexture.active = null;
                var png = tex.EncodeToPNG();
                File.WriteAllBytes(Path.Combine(Application.persistentDataPath, "debug_view.png"), png);
                Destroy(tex);
                rt.Release();
                Destroy(rt);
                Debug.Log("DebugCapture saved " + png.Length);
            }
            catch (System.Exception e)
            {
                Debug.LogWarning("DebugCapture: " + e.Message);
            }
        }
    }
}
