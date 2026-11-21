using System.Collections;
using UnityEngine;
#if UNITY_ANDROID && !UNITY_EDITOR
using Unity.XR.OpenXR.Features.PICOSupport;
#endif

namespace Companion
{
    /// <summary>开启 PICO 彩色透视。启动/恢复时都要重新开，暂停会让系统关掉透视。</summary>
    public class PassthroughEnabler : MonoBehaviour
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Boot()
        {
            if (FindObjectOfType<PassthroughEnabler>() == null)
                new GameObject("PassthroughBootstrap").AddComponent<PassthroughEnabler>();
        }
        IEnumerator Start()
        {
            yield return EnableLoop();
        }

        void OnApplicationPause(bool paused)
        {
            if (!paused)
            {
                StopAllCoroutines();
                StartCoroutine(EnableLoop());
            }
        }

        void OnApplicationFocus(bool focus)
        {
            if (focus)
            {
                StopAllCoroutines();
                StartCoroutine(EnableLoop());
            }
        }

        IEnumerator EnableLoop()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            for (int i = 0; i < 20; i++)
            {
                try
                {
                    var cam = Camera.main;
                    Debug.Log("PassthroughEnabler: cam=" + (cam != null) + " clear=" + (cam != null ? cam.clearFlags.ToString() : "-") + " bg=" + (cam != null ? cam.backgroundColor.ToString() : "-"));
                    PassthroughFeature.EnableVideoSeeThrough = true;
                    bool ok = PassthroughFeature.EnableSeeThroughManual(true);
                    Debug.Log("PassthroughEnabler: try=" + i + " EnableSeeThroughManual=" + ok);
                    if (ok)
                    {
                        PassthroughFeature.PassthroughStart();
                        Debug.Log("PassthroughEnabler: passthrough started");
                        yield break;
                    }
                }
                catch (System.Exception e)
                {
                    Debug.LogWarning("PassthroughEnabler: " + e.Message);
                }
                yield return new WaitForSeconds(0.5f);
            }
            Debug.LogWarning("PassthroughEnabler: gave up");
#else
            yield break;
#endif
        }
    }
}
