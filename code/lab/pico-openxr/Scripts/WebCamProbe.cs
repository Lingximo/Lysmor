using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Android;

namespace Companion
{
    /// <summary>验证 PICO 的 Android Camera2 是否能通过 WebCamTexture 取到彩色帧。</summary>
    public class WebCamProbe : MonoBehaviour
    {
        IEnumerator Start()
        {
            if (!Permission.HasUserAuthorizedPermission(Permission.Camera))
            {
                Permission.RequestUserPermission(Permission.Camera);
                yield return new WaitForSeconds(3f);
            }

            var devices = WebCamTexture.devices;
            Debug.Log("WebCamProbe: devices=" + devices.Length);
            for (int i = 0; i < devices.Length; i++)
                Debug.Log($"WebCamProbe: [{i}] {devices[i].name} front={devices[i].isFrontFacing}");

            if (devices.Length == 0) yield break;
            var tex = new WebCamTexture(devices[0].name, 640, 480, 30);
            tex.Play();
            yield return new WaitForSeconds(4f);
            Debug.Log($"WebCamProbe: playing={tex.isPlaying} size={tex.width}x{tex.height}");

            if (tex.width > 16 && tex.height > 16)
            {
                var px = tex.GetPixels32();
                int nonBlack = 0;
                for (int i = 0; i < px.Length; i += 37)
                    if (px[i].r + px[i].g + px[i].b > 24) nonBlack++;
                Debug.Log("WebCamProbe: nonBlackSamples=" + nonBlack);
                try
                {
                    var img = new Texture2D(tex.width, tex.height, TextureFormat.RGBA32, false);
                    img.SetPixels32(px);
                    img.Apply();
                    File.WriteAllBytes(Path.Combine(Application.persistentDataPath, "webcam_probe.png"), img.EncodeToPNG());
                    Debug.Log("WebCamProbe: saved " + Path.Combine(Application.persistentDataPath, "webcam_probe.png"));
                }
                catch (System.Exception e) { Debug.LogWarning("WebCamProbe: save failed " + e.Message); }
            }
            tex.Stop();
        }
    }
}
