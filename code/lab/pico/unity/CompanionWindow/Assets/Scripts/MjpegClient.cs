using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.UI;

namespace Companion
{
    /// <summary>
    /// 从电脑的 /panel.mjpg 取她的画面，贴到浮窗上。
    /// 网络线程收 JPEG，主线程解成 Texture2D。
    /// </summary>
    public class MjpegClient : MonoBehaviour
    {
        public string url = "http://192.168.1.2:8014/panel.mjpg";
        public RawImage target;
        public UnityEngine.UI.Text status;

        readonly ConcurrentQueue<byte[]> frames = new ConcurrentQueue<byte[]>();
        Texture2D tex;
        CancellationTokenSource cts;
        volatile bool running;

        void Start()
        {
            if (target == null) target = GetComponent<RawImage>();
            tex = new Texture2D(2, 2, TextureFormat.RGB24, false);
            cts = new CancellationTokenSource();
            running = true;
            _ = Task.Run(() => Loop(cts.Token));
        }

        async Task Loop(CancellationToken token)
        {
            var http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
            while (!token.IsCancellationRequested)
            {
                try
                {
                    using var resp = await http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, token);
                    resp.EnsureSuccessStatusCode();
                    using var stream = await resp.Content.ReadAsStreamAsync();
                    await ReadJpegs(stream, token);
                }
                catch (Exception e)
                {
                    if (!token.IsCancellationRequested)
                        Debug.LogWarning("panel stream: " + e.Message);
                        if (status != null) status.text = "画面重连中";
                }
                await Task.Delay(1000, token);
            }
        }

        async Task ReadJpegs(Stream stream, CancellationToken token)
        {
            var buf = new byte[64 * 1024];
            var frame = new MemoryStream();
            bool inFrame = false;
            int prev = -1;
            while (!token.IsCancellationRequested)
            {
                int n = await stream.ReadAsync(buf, 0, buf.Length, token);
                if (n <= 0) return;
                for (int i = 0; i < n; i++)
                {
                    int b = buf[i];
                    if (!inFrame)
                    {
                        if (prev == 0xFF && b == 0xD8)   // JPEG SOI
                        {
                            frame.SetLength(0);
                            frame.WriteByte(0xFF);
                            frame.WriteByte(0xD8);
                            inFrame = true;
                        }
                    }
                    else
                    {
                        frame.WriteByte((byte)b);
                        if (prev == 0xFF && b == 0xD9)   // JPEG EOI
                        {
                            var bytes = frame.ToArray();
                            while (frames.Count > 2) frames.TryDequeue(out _);
                            frames.Enqueue(bytes);
                            inFrame = false;
                        }
                    }
                    prev = b;
                }
            }
        }

        void Update()
        {
            if (frames.TryDequeue(out var jpg))
            {
                if (tex.LoadImage(jpg))
                {
                    if (target != null) target.texture = tex;
                    if (status != null) status.text = "画面 OK";
                }
            }
        }

        void OnDestroy()
        {
            running = false;
            cts?.Cancel();
        }
    }
}
