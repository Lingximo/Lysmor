using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.Hands;

namespace Companion
{
    /// <summary>最小 OpenXR 手部探针：不渲染手，只打印 XR Hands 关节和捏合距离。</summary>
    public class OpenXRHandProbe : MonoBehaviour
    {
        XRHandSubsystem subsystem;
        float nextLog;
        bool found;

        void Start()
        {
            var mgr = UnityEngine.XR.Management.XRGeneralSettings.Instance != null
                ? UnityEngine.XR.Management.XRGeneralSettings.Instance.Manager : null;
            if (mgr != null && !mgr.isInitializationComplete)
            {
                Debug.Log("OpenXRHandProbe: forcing loader init");
                mgr.InitializeLoaderSync();
                if (mgr.activeLoader != null)
                {
                    mgr.StartSubsystems();
                    Debug.Log("OpenXRHandProbe: loader=" + mgr.activeLoader.name);
                }
                else Debug.LogWarning("OpenXRHandProbe: activeLoader null");
            }
        }

        void Update()
        {
            if (subsystem == null)
            {
                var list = new List<XRHandSubsystem>();
                SubsystemManager.GetSubsystems(list);
                if (list.Count > 0) subsystem = list[0];
            }

            if (subsystem == null)
            {
                if (Time.time > nextLog)
                {
                    nextLog = Time.time + 2f;
                    Debug.Log("OpenXRHandProbe: no XRHandSubsystem");
                }
                return;
            }

            if (!found)
            {
                found = true;
                Debug.Log("OpenXRHandProbe: subsystem=" + subsystem.running);
            }

            var hand = subsystem.rightHand;
            bool tracked = hand.isTracked;
            if (Time.time > nextLog)
            {
                nextLog = Time.time + 1f;
                string tip = "none", thumb = "none";
                if (hand.GetJoint(XRHandJointID.IndexTip).TryGetPose(out var p))
                    tip = p.position.ToString("F3");
                if (hand.GetJoint(XRHandJointID.ThumbTip).TryGetPose(out var t))
                    thumb = t.position.ToString("F3");
                Debug.Log($"OpenXRHandProbe tracked={tracked} tip={tip} thumb={thumb}");
            }
        }
    }
}
