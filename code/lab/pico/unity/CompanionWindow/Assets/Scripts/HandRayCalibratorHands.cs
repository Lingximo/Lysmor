using UnityEngine;
using Unity.XR.PXR;

namespace Companion
{
    /// <summary>双手校准：右手保持指向，左手捏合后移动来拖动手部射线偏移。
    /// 不依赖控制器，避免拿手柄时手部追踪被系统切走。</summary>
    public class HandRayCalibratorHands : MonoBehaviour
    {
        public PXRHandRay ray;
        public float gain = 1.0f;

        HandAimState leftAim;
        HandJointLocations leftJoints;
        bool adjusting;
        Vector3 lastPos;
        float nextHint;

        void Start()
        {
            if (ray == null) ray = FindObjectOfType<PXRHandRay>();
            Debug.Log("HandRayCalibratorHands: 右手指目标，左手捏合后移动调位置，松开保存");
        }

        void Update()
        {
            if (ray == null) return;

            bool aimOk = PXR_HandTracking.GetAimState(HandType.HandLeft, ref leftAim);
            bool pinch = aimOk && (((leftAim.aimStatus & HandAimStatus.AimIndexPinching) != 0)
                                  || leftAim.touchStrengthRay > 0.75f);

            bool jointOk = PXR_HandTracking.GetJointLocations(HandType.HandLeft, ref leftJoints)
                           && leftJoints.jointLocations != null;
            Vector3 pos = Vector3.zero;
            if (jointOk)
            {
                int wrist = (int)HandJoint.JointWrist;
                if (wrist < leftJoints.jointLocations.Length)
                    pos = leftJoints.jointLocations[wrist].pose.Position.ToVector3();
            }

            if (!pinch || !jointOk)
            {
                if (adjusting)
                {
                    adjusting = false;
                    ray.SaveCalibration();
                    Debug.Log("HandRayCalibratorHands: saved " + ray.calibration);
                }
                return;
            }

            if (!adjusting)
            {
                adjusting = true;
                lastPos = pos;
                return;
            }

            Vector3 delta = pos - lastPos;
            lastPos = pos;
            if (delta.sqrMagnitude > 0.0000001f)
            {
                ray.calibration += delta * gain;
                if (Time.time > nextHint)
                {
                    nextHint = Time.time + 0.4f;
                    Debug.Log("HandRayCalibratorHands: " + ray.calibration);
                }
            }
        }
    }
}
