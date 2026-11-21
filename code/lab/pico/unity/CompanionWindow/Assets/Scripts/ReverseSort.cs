using UnityEngine;
using Live2D.Cubism.Core;

namespace Companion
{
    public class ReverseSort : MonoBehaviour
    {
        CubismModel model;
        MeshRenderer[] rs;
        void LateUpdate()
        {
            if (model == null)
            {
                model = GetComponent<CubismModel>();
                if (model == null) model = GetComponentInChildren<CubismModel>();
                if (model == null) return;
            }
            if (rs == null || rs.Length != model.Drawables.Length)
            {
                rs = new MeshRenderer[model.Drawables.Length];
                for (int i = 0; i < rs.Length; i++) rs[i] = model.Drawables[i].GetComponent<MeshRenderer>();
            }
            for (int i = 0; i < rs.Length; i++)
                if (rs[i] != null) rs[i].sortingOrder = rs.Length - 1 - i;
        }
    }
}
