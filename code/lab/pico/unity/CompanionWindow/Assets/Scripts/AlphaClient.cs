using System;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace Companion
{
    /// <summary>拉取带 alpha 的 PNG 帧（原 Web Live2D 渲染），不再做色度键。</summary>
    public class AlphaClient : MonoBehaviour
    {
        public RawImage target;
        public string url = "http://192.168.1.2:8003/panel/frame.png";
        public int intervalMs = 80;
        public UnityEngine.UI.Text status;

        async void Start()
        {
            while (true)
            {
                try
                {
                    using var req = UnityWebRequest.Get(url);
                    req.downloadHandler = new DownloadHandlerTexture(false);
                    req.timeout = 10;
                    var op = req.SendWebRequest();
                    while (!op.isDone) await Task.Yield();
                    if (req.result == UnityWebRequest.Result.Success)
                    {
                        var tex = DownloadHandlerTexture.GetContent(req);
                        if (tex != null && target != null)
                        {
                            var old = target.texture;
                            target.texture = tex;
                            if (status != null) status.text = "画面已连接";
                            if (old != null) Destroy(old);
                        }
                    }
                }
                catch (Exception e)
                {
                    Debug.LogWarning("alpha: " + e.Message);
                    if (status != null) status.text = "电脑画面未连接";
                }
                await Task.Delay(intervalMs);
            }
        }
    }
}
