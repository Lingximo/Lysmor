"""TA的「认人」底层：SCRFD-10G 检测 + ArcFace R50 特征（本地、离线）。

为什么换掉 Haar/LBPH：
    Haar 侧脸一到就丢，LBPH 是像素匹配，换个灯就崩。
    SCRFD + ArcFace（insightface buffalo_l）是工业标准：
    侧脸/遮挡能检出，512 维特征对光照不敏感。

接口（只做计算，判断留给上层）：
    det = FaceDetector()
    faces = det.detect(bgr)      # [{"box":[x1,y1,x2,y2],"score":0.9,"kps":[[x,y]*5]}]
    vec   = det.embed(bgr, face) # np.float32(512)，已 L2 归一化
    cosine(v1, v2)

依赖（装在 lab\\vision\\pylibs，不碰她的 venv）：opencv-python-headless、onnxruntime、numpy
模型：models\\buffalo_l\\det_10g.onnx、w600k_r50.onnx

隔离：本文件不开端口、不写 state/记忆，只被 lab 下的脚本调用。
"""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PYLIBS = os.path.join(HERE, "pylibs")
MODELS = os.path.join(HERE, "models", "buffalo_l")

if os.path.isdir(PYLIBS) and PYLIBS not in sys.path:
    sys.path.insert(0, PYLIBS)

import cv2  # noqa: E402
import onnxruntime as ort  # noqa: E402

DET_PATH = os.path.join(MODELS, "det_10g.onnx")
REC_PATH = os.path.join(MODELS, "w600k_r50.onnx")

# ArcFace 的 112x112 五点标准位置
_REF = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


def _distance2bbox(points, distance):
    return np.stack([
        points[:, 0] - distance[:, 0],
        points[:, 1] - distance[:, 1],
        points[:, 0] + distance[:, 2],
        points[:, 1] + distance[:, 3],
    ], axis=-1)


def _distance2kps(points, distance):
    out = []
    for i in range(0, distance.shape[1], 2):
        out.append(points[:, 0] + distance[:, i])
        out.append(points[:, 1] + distance[:, i + 1])
    return np.stack(out, axis=-1)


def cosine(a, b) -> float:
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return 0.0 if na == 0 or nb == 0 else float(np.dot(a, b) / (na * nb))


class FaceDetector:
    """SCRFD 检测 + ArcFace 特征。第一次调用才建 session。"""

    def __init__(self, det_size=(640, 640), score_thresh=0.5, providers=None):
        for p in (DET_PATH, REC_PATH):
            if not os.path.isfile(p):
                raise FileNotFoundError("缺模型：%s" % p)
        self.det_size = det_size
        self.score_thresh = score_thresh
        so = ort.SessionOptions()
        so.log_severity_level = 3
        prov = providers or ["CPUExecutionProvider"]
        self._det = ort.InferenceSession(DET_PATH, so, providers=prov)
        self._rec = ort.InferenceSession(REC_PATH, so, providers=prov)
        self._det_in = self._det.get_inputs()[0].name
        self._rec_in = self._rec.get_inputs()[0].name

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        dw, dh = self.det_size
        scale = min(dw / w, dh / h)
        nw, nh = int(w * scale), int(h * scale)
        canvas = np.zeros((dh, dw, 3), dtype=np.uint8)
        canvas[:nh, :nw] = cv2.resize(bgr, (nw, nh))
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128, (dw, dh),
                                     (127.5, 127.5, 127.5), swapRB=True)
        outs = self._det.run(None, {self._det_in: blob})
        n = len(outs) // 3
        faces = []
        for i, stride in enumerate((8, 16, 32)[:n]):
            scores = outs[i].reshape(-1)
            bbox_preds = outs[i + n].reshape(-1, 4)
            kps_preds = outs[i + 2 * n].reshape(-1, 10)
            fh, fw = dh // stride, dw // stride
            centers = np.stack(np.mgrid[:fh, :fw][::-1], axis=-1).astype(np.float32)
            centers = (centers * stride).reshape(-1, 2)
            centers = np.stack([centers, centers], axis=1).reshape(-1, 2)
            pos = np.where(scores >= self.score_thresh)[0]
            if pos.size == 0:
                continue
            bboxes = _distance2bbox(centers[pos], bbox_preds[pos] * stride)
            kps = _distance2kps(centers[pos], kps_preds[pos] * stride).reshape(-1, 5, 2)
            for j, idx in enumerate(pos):
                faces.append({
                    "box": (bboxes[j] / scale).tolist(),
                    "score": float(scores[idx]),
                    "kps": (kps[j] / scale).tolist(),
                })
        faces = self._nms(faces)
        faces.sort(key=lambda f: f["score"], reverse=True)
        return faces

    @staticmethod
    def _nms(faces, iou_thresh=0.4):
        if not faces:
            return faces
        boxes = np.array([[b["box"][0], b["box"][1],
                           b["box"][2] - b["box"][0],
                           b["box"][3] - b["box"][1]] for b in faces], dtype=np.float32)
        scores = np.array([b["score"] for b in faces], dtype=np.float32)
        keep = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), 0.3, iou_thresh)
        if len(keep) == 0:
            return []
        return [faces[int(i)] for i in np.array(keep).ravel()]

    def align(self, bgr, face):
        kps = np.asarray(face["kps"], dtype=np.float32)
        M, _ = cv2.estimateAffinePartial2D(kps, _REF, method=cv2.LMEDS)
        if M is None:
            return None
        return cv2.warpAffine(bgr, M, (112, 112), borderValue=0.0)

    def embed(self, bgr, face):
        chip = self.align(bgr, face)
        if chip is None:
            return None
        blob = cv2.dnn.blobFromImage(chip, 1.0 / 128, (112, 112),
                                     (127.5, 127.5, 127.5), swapRB=True)
        vec = self._rec.run(None, {self._rec_in: blob})[0].ravel().astype(np.float32)
        n = np.linalg.norm(vec)
        return vec / n if n else vec

    def __repr__(self):
        return "FaceDetector(%s + %s)" % (
            os.path.basename(DET_PATH), os.path.basename(REC_PATH))


def open_camera(index: int = 0, width: int = 1280, height: int = 720):
    """按 MSMF → DSHOW → 默认 的顺序尝试打开摄像头。

    2026-11-06：这台机器的 VC-005 在 OpenCV 5 下三种后端都打不开
    （之前 4.x 能打开但全黑）。换新摄像头后这里应该直接可用。
    """
    for backend, label in ((cv2.CAP_MSMF, "MSMF"), (cv2.CAP_DSHOW, "DSHOW"), (cv2.CAP_ANY, "ANY")):
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            ok, frame = cap.read()
            if ok and frame is not None:
                return cap, label
            cap.release()
    return None, "none"


def identity_of(name: str) -> str:
    """把「凌曦沫_戴眼镜」这种别名归到同一个人：取下划线前的部分。"""
    return (name or "").split("_")[0].strip()


def identify(vec, people: dict, thresh_known: float = 0.5, min_margin: float = 0.08) -> dict:
    """按"人"而不是"条目"比较：同一个人可以有多个样子（不戴/戴眼镜/扎头发）。

    返回 {"who", "score", "margin", "state"}；
    state = known / stranger / no_enrollment
    """
    if not people or vec is None:
        return {"who": None, "score": 0.0, "margin": 0.0, "state": "no_enrollment"}

    best_by_person = {}
    for key, ref in people.items():
        who = identity_of(key)
        score = float(cosine(vec, ref))
        if score > best_by_person.get(who, -1.0):
            best_by_person[who] = score

    ranked = sorted(best_by_person.items(), key=lambda kv: kv[1], reverse=True)
    best_who, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = best - second
    known = best >= thresh_known and margin >= min_margin
    return {
        "who": best_who if known else None,
        "score": round(best, 3),
        "margin": round(margin, 3),
        "state": "known" if known else "stranger",
    }


def _looks_like_real_camera(frame) -> bool:
    """挡住采集卡/虚拟摄像头：全黑、纯静态画面、或者只有几个颜色。

    2026-11-09：VC-005 采集卡在没接信号时会输出"无信号"蓝黑图，
    和她要看的真实画面差别很大，这里用方差 + 亮度粗筛。
    """
    try:
        import numpy as np

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) > 25 and float(gray.std()) > 8
    except Exception:  # noqa: BLE001
        return True


def pick_camera(max_index: int = 4, width: int = 1280, height: int = 720):
    """自动找真摄像头，返回 (cap, label, index)。

    顺序：先按 index 扫，取第一个"像真画面"的；
    都不像就退回第一个能打开的（至少别让调用方拿到 None）。
    """
    fallback = None
    for idx in range(max_index):
        cap, label = open_camera(idx, width, height)
        if cap is None:
            continue
        ok = False
        frame = None
        for _ in range(6):
            ok, frame = cap.read()
            if ok and frame is not None:
                break
        if not ok or frame is None:
            cap.release()
            continue
        if fallback is None:
            fallback = (cap, label, idx)
            continue
        if _looks_like_real_camera(frame):
            if fallback is not None and fallback[0] is not cap:
                fallback[0].release()
            return cap, label, idx
        cap.release()
    return fallback if fallback else (None, "none", -1)


if __name__ == "__main__":
    import json

    if len(sys.argv) < 2:
        print("用法: python face_lib.py <图片>")
        raise SystemExit(2)
    img = cv2.imread(sys.argv[1])
    if img is None:
        print("读不到图：", sys.argv[1])
        raise SystemExit(2)
    det = FaceDetector()
    faces = det.detect(img)
    print("检出 %d 张脸" % len(faces))
    for f in faces[:5]:
        v = det.embed(img, f)
        print(json.dumps({"score": round(f["score"], 3),
                          "box": [round(x, 1) for x in f["box"]],
                          "vec_dim": int(v.size) if v is not None else 0},
                         ensure_ascii=False))
