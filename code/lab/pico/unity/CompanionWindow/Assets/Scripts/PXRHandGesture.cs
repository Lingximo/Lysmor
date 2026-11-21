using UnityEngine;
using Unity.XR.PXR;

namespace Companion
{
    /// <summary>整只手握拳判定：四指指尖都靠近掌心。
    ///
    /// 2026-11-16 改：原来「平均距离 &lt; 0.090 就算握拳」太敏感（张开约 0.111，
    /// 握拳 0.046~0.081，0.090 几乎半握就算数）。现在只有**握拳完成**才判定：
    ///   1) 平均距离要收紧到 COMPLETE 以下；
    ///   2) 并且连续保持 HOLD 秒（手捋过去、晃一下不算）；
    ///   3) 松开必须开到 RELEASE 以上才解除（迟滞，边缘抖动不会反复触发）。
    /// 手追踪丢失（PXR 给全零关节，平均 &lt; LOST）一律不算握拳，并清状态。
    /// </summary>
    public static class PXRHandGesture
    {
        // 阈值：0.046~0.081 是实测“握紧”的范围，0.090 是旧的松阈值
        const float COMPLETE = 0.070f;   // 收紧到这个程度才算握上（旧 0.090）
        const float RELEASE = 0.088f;    // 松到这个程度才算松开（迟滞）
        const float HOLD = 0.10f;        // 连续收紧这么久才判定，秒
        const float LOST = 0.02f;        // 低于这个值 = 关节无效/追踪丢失

        static readonly int[] Tips =
        {
            (int)HandJoint.JointIndexTip,
            (int)HandJoint.JointMiddleTip,
            (int)HandJoint.JointRingTip,
            (int)HandJoint.JointLittleTip,
        };

        // 每只手各自的状态：_since < 0 表示“还没开始收紧”
        static readonly float[] _since = { -1f, -1f };
        static readonly bool[] _latched = { false, false };

        public static bool TryGetFist(HandType type, out float average)
        {
            average = 999f;
            int hand = type == HandType.HandLeft ? 1 : 0;

            var locs = new HandJointLocations();
            if (!PXR_HandTracking.GetJointLocations(type, ref locs) || locs.jointLocations == null)
            {
                Reset(hand);
                return false;
            }

            int palmId = (int)HandJoint.JointPalm;
            if (palmId >= locs.jointLocations.Length)
            {
                Reset(hand);
                return false;
            }

            Vector3 palm = locs.jointLocations[palmId].pose.Position.ToVector3();
            float sum = 0f;
            float maxTip = 0f;
            int n = 0;
            for (int i = 0; i < Tips.Length; i++)
            {
                int id = Tips[i];
                if (id >= locs.jointLocations.Length) continue;
                Vector3 tip = locs.jointLocations[id].pose.Position.ToVector3();
                float d = Vector3.Distance(palm, tip);
                sum += d;
                if (d > maxTip) maxTip = d;
                n++;
            }
            if (n == 0)
            {
                Reset(hand);
                return false;
            }

            average = sum / n;
            // 手追踪丢失时 PXR 会返回全零关节，不能当成握拳
            if (average < LOST)
            {
                Reset(hand);
                return false;
            }

            float now = Time.time;
            if (average <= COMPLETE)
            {
                if (!_latched[hand])
                {
                    if (_since[hand] < 0f) _since[hand] = now;
                    if (now - _since[hand] >= HOLD)
                    {
                        _latched[hand] = true;
                        Debug.Log($"[手势] 握拳完成 avg={average:F3} max={maxTip:F3}");
                    }
                }
            }
            else if (average >= RELEASE)
            {
                if (_latched[hand]) Debug.Log($"[手势] 松开 avg={average:F3}");
                Reset(hand);
            }
            // COMPLETE..RELEASE 之间是迟滞带：保持上一次状态，不来回跳

            return _latched[hand];
        }

        static void Reset(int hand)
        {
            _since[hand] = -1f;
            _latched[hand] = false;
        }
    }
}
