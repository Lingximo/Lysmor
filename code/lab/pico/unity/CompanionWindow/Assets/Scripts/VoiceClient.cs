using System;
using System.Collections.Generic;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Android;
using UnityEngine.UI;
using UnityEngine.Networking;

namespace Companion
{
    /// <summary>
    /// Pico 麦克风 → 电脑 8003；她的回复文字 + mp3 → Pico 播放。
    /// 复用现有视频通话的 WebSocket，不新建协议。
    /// </summary>
    public class VoiceClient : MonoBehaviour
    {
        public string wsUrl = "ws://192.168.1.2:8003/ws?sid=pico";
        public AudioSource speaker;
        public Text caption;
        public Text status;

        ClientWebSocket ws;
        CancellationTokenSource cts;
        readonly Queue<string> pendingText = new Queue<string>();
        readonly Queue<string> pendingCaption = new Queue<string>();
        readonly Queue<string> pendingStatus = new Queue<string>();
        bool recording;
        bool micSuspended;
        string micDevice;
        AudioClip micClip;
        int lastPos;
        float silence;
        bool hadSpeech;
        float muteUntil;
        float speechTime;
        readonly List<float> buffer = new List<float>();
        const int SampleRate = 16000;

        void Awake()
        {
            Application.runInBackground = true;
            Screen.sleepTimeout = SleepTimeout.NeverSleep;
        }

        void OnApplicationPause(bool paused)
        {
            if (!paused) ResumeVoice();
        }

        void OnApplicationFocus(bool focus)
        {
            if (focus) ResumeVoice();
        }

        void ResumeVoice()
        {
            try
            {
                StartMic();
                if (ws == null || ws.State != WebSocketState.Open)
                {
                    if (cts == null || cts.IsCancellationRequested)
                        cts = new CancellationTokenSource();
                    _ = Connect(cts.Token);
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("voice resume: " + e.Message);
            }
        }

        async void Start()
        {
            if (speaker == null)
            {
                speaker = gameObject.AddComponent<AudioSource>();
                speaker.spatialBlend = 0f;
            }
            if (!Permission.HasUserAuthorizedPermission(Permission.Microphone))
            {
                Permission.RequestUserPermission(Permission.Microphone);
            }
            cts = new CancellationTokenSource();
            _ = Connect(cts.Token);
            StartMic();
        }

        void StartMic()
        {
            if (Microphone.devices.Length == 0)
            {
                Debug.LogWarning("no microphone");
                return;
            }
            micDevice = Microphone.devices[0];
            Microphone.GetDeviceCaps(micDevice, out int minFreq, out int maxFreq);
            Debug.Log($"mic caps {minFreq}-{maxFreq}");
            if (Microphone.IsRecording(micDevice)) Microphone.End(micDevice);
            micClip = Microphone.Start(micDevice, true, 2, SampleRate);
            lastPos = 0;
            recording = true;
            Debug.Log("mic started: " + micDevice);
        }

        async Task Connect(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    ws = new ClientWebSocket();
                    await ws.ConnectAsync(new Uri(wsUrl), token);
                    Debug.Log("voice ws connected");
                    if (status != null) status.text = "语音：说「TA」唤醒";
                    await ReceiveLoop(token);
                }
                catch (Exception e)
                {
                    Debug.LogWarning("voice ws: " + e.Message);
                }
                await Task.Delay(1500, token);
            }
        }

        async Task ReceiveLoop(CancellationToken token)
        {
            var buf = new byte[64 * 1024];
            var ms = new MemoryStream();
            while (ws != null && ws.State == WebSocketState.Open && !token.IsCancellationRequested)
            {
                var r = await ws.ReceiveAsync(new ArraySegment<byte>(buf), token);
                if (r.MessageType == WebSocketMessageType.Close) break;
                ms.Write(buf, 0, r.Count);
                if (!r.EndOfMessage) continue;
                string json = Encoding.UTF8.GetString(ms.ToArray());
                ms.SetLength(0);
                HandleJson(json);
            }
        }

        void HandleJson(string json)
        {
            try
            {
                var obj = JsonUtility.FromJson<Reply>(json);
                if (obj == null) return;
                if (obj.type == "status" && !string.IsNullOrEmpty(obj.status))
                {
                    lock (pendingStatus) pendingStatus.Enqueue(obj.status);
                }
                if ((obj.type == "delta" || obj.type == "reply") && !string.IsNullOrEmpty(obj.text))
                {
                    Debug.Log("voice " + obj.type + ": " + obj.text.Substring(0, Mathf.Min(60, obj.text.Length)));
                    lock (pendingCaption)
                    {
                        if (obj.type == "reply")
                        {
                            // reply 是最终整句，替换掉流式片段，避免同一句字幕出现两次
                            pendingCaption.Clear();
                            pendingCaption.Enqueue("\0" + obj.text);
                        }
                        else
                        {
                            pendingCaption.Enqueue(obj.text);
                        }
                    }
                }
                if ((obj.type == "audio" || obj.type == "reply") && !string.IsNullOrEmpty(obj.audio))
                {
                    // 一收到音频就先闭嘴，不等下载完，防止她自己的声音被收进来
                    // 等音频真正开始播放时再锁麦克风，收到包时不提前锁 2.5 秒
                    lock (pendingText) pendingText.Enqueue(obj.audio);
                }
                else if (obj.type == "error")
                {
                    Debug.Log("server: " + obj.message);
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("json: " + e.Message);
            }
        }

        [Serializable]
        class Reply
        {
            public string type;
            public string text;
            public string delta;
            public string status;
            public string audio;
            public string format;
            public string message;
        }

        void SuspendMic()
        {
            micSuspended = true;
            recording = false;
            try { if (Microphone.IsRecording(micDevice)) Microphone.End(micDevice); } catch { }
        }

        void ResumeMic()
        {
            micSuspended = false;
            if (!recording) StartMic();
        }

        void Update()
        {
            if (recording && !micSuspended && micClip != null)
            {
                int pos = Microphone.GetPosition(micDevice);
                if (pos != lastPos)
                {
                    int len = (pos - lastPos + micClip.samples) % micClip.samples;
                    if (len > 0)
                    {
                        var data = new float[len];
                        micClip.GetData(data, lastPos);
                        lastPos = pos;
                        ProcessSamples(data);
                    }
                }
            }
            lock (pendingStatus)
            {
                if (pendingStatus.Count > 0 && status != null)
                {
                    string st = pendingStatus.Dequeue();
                    status.text = st == "sleep" ? "待唤醒 · 说「TA」" : "在听…";
                }
            }
            lock (pendingCaption)
            {
                if (pendingCaption.Count > 0 && caption != null)
                {
                    string line = pendingCaption.Dequeue();
                    if (line.StartsWith("\0"))
                    {
                        caption.text = line.Substring(1);
                    }
                    else
                    {
                        caption.text = string.IsNullOrEmpty(caption.text) ? line : (caption.text + " " + line);
                    }
                    if (caption.text.Length > 160) caption.text = caption.text.Substring(caption.text.Length - 160);
                }
            }
            if (speaker != null && !speaker.isPlaying)
            {
                string b64 = null;
                lock (pendingText)
                {
                    if (pendingText.Count > 0) b64 = pendingText.Dequeue();
                }
                if (b64 != null) _ = PlayMp3(b64);
            }
        }

        void ProcessSamples(float[] data)
        {
            // 她正在说话时闭嘴：喇叭声会被麦克风收回去，形成自言自语
            if (Time.time < muteUntil)
            {
                buffer.Clear();
                silence = 0f;
                hadSpeech = false;
                return;
            }
            float sum = 0;
            foreach (var s in data) sum += s * s;
            float rms = Mathf.Sqrt(sum / Mathf.Max(1, data.Length));
            buffer.AddRange(data);
            float dt = data.Length / (float)SampleRate;
            if (rms >= 0.035f)
            {
                silence = 0f;
                speechTime += dt;
                if (speechTime >= 0.35f) hadSpeech = true;
            }
            else
            {
                silence += dt;
            }

            // 说了一段（或静音超过 0.6 秒）就切一块发过去
            if (buffer.Count >= SampleRate * 3 || (silence > 0.4f && buffer.Count > SampleRate * 0.8f))
            {
                if (hadSpeech && buffer.Count > SampleRate * 0.6f)
                {
                    SendWav(buffer);
                }
                hadSpeech = false;
                buffer.Clear();
                silence = 0f;
            }
        }

        async void SendWav(List<float> samples)
        {
            if (ws == null || ws.State != WebSocketState.Open) return;
            try
            {
                byte[] wav = ToWav(samples, SampleRate);
                await ws.SendAsync(new ArraySegment<byte>(wav), WebSocketMessageType.Binary,
                    true, cts.Token);
                Debug.Log("sent wav " + wav.Length);
            }
            catch (Exception e)
            {
                Debug.LogWarning("send: " + e.Message);
            }
        }

        static byte[] ToWav(List<float> samples, int rate)
        {
            int n = samples.Count;
            var ms = new MemoryStream(44 + n * 2);
            var bw = new BinaryWriter(ms);
            bw.Write(Encoding.ASCII.GetBytes("RIFF"));
            bw.Write(36 + n * 2);
            bw.Write(Encoding.ASCII.GetBytes("WAVEfmt "));
            bw.Write(16);
            bw.Write((short)1);
            bw.Write((short)1);
            bw.Write(rate);
            bw.Write(rate * 2);
            bw.Write((short)2);
            bw.Write((short)16);
            bw.Write(Encoding.ASCII.GetBytes("data"));
            bw.Write(n * 2);
            foreach (var s in samples)
            {
                bw.Write((short)Mathf.Clamp(s * 32767f, -32768f, 32767f));
            }
            bw.Flush();
            return ms.ToArray();
        }

        async Task PlayMp3(string b64)
        {
            try
            {
                byte[] mp3 = Convert.FromBase64String(b64);
                string path = Path.Combine(Application.persistentDataPath, "reply.mp3");
                File.WriteAllBytes(path, mp3);
                using var req = UnityWebRequestMultimedia.GetAudioClip("file://" + path, AudioType.MPEG);
                req.SendWebRequest();
                while (!req.isDone) await Task.Yield();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogWarning("mp3: " + req.error);
                    return;
                }
                var clip = DownloadHandlerAudioClip.GetContent(req);
                if (clip != null)
                {
                    speaker.clip = clip;
                    muteUntil = Time.time + clip.length + 0.5f;
                    buffer.Clear();
                    silence = 0f;
                    hadSpeech = false;
                    SuspendMic();
                    speaker.Play();
                    await Task.Delay((int)(clip.length * 1000f) + 600);
                    ResumeMic();
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("play: " + e.Message);
            }
        }

        void OnDestroy()
        {
            cts?.Cancel();
            Microphone.End(micDevice);
        }
    }
}
