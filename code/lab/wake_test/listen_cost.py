# -*- coding: utf-8 -*-
"""待机唤醒的「成本」实测：只测本地开销，证明不发任何网络请求。

跑 20 秒麦克风，做能量检测（相当于唤醒词之前的 VAD），打印：
  每秒的均方根音量、被判定为"有声音"的帧数、CPU 时间、内存占用。
全程不发一个网络请求 —— 所以 token = 0。

用法：python lab\\wake_test\\listen_cost.py [秒数]
"""
import os
import sys
import time

try:                       # Linux/macOS 有 resource；Windows 没有
    import resource
except Exception:          # noqa: BLE001
    resource = None

try:
    import numpy as np
    import sounddevice as sd
except Exception as exc:  # noqa: BLE001
    print("缺库：%s" % exc)
    raise SystemExit(2)

SR = 16000
BLOCK = 1600          # 100ms 一帧
THRESHOLD = 0.012     # 均方根音量阈值（安静房间约 0.002~0.006）


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    frames = int(secs * SR / BLOCK)
    voiced = 0
    rms_list = []
    t0 = time.process_time()
    wall0 = time.time()

    print("监听 %.0f 秒（16000Hz / 100ms 一帧），全程不联网…" % secs)
    with sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=BLOCK) as st:
        for i in range(frames):
            data, _overflow = st.read(BLOCK)
            x = data[:, 0]
            rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
            rms_list.append(rms)
            if rms > THRESHOLD:
                voiced += 1
            if i % 10 == 9:
                print("  %2.0fs  rms≈%.4f  有声帧=%d" % ((i + 1) / 10.0, rms, voiced))
    cpu = time.process_time() - t0
    wall = time.time() - wall0

    # 本进程峰值内存
    peak_mb = -1
    try:
        if resource is not None:
            peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        else:
            import psutil
            peak_mb = psutil.Process(os.getpid()).memory_info().rss / 1048576.0
    except Exception:  # noqa: BLE001
        peak_mb = -1

    print("")
    print("总帧数          %d" % frames)
    print("有声帧          %d (%.1f%%)" % (voiced, voiced * 100.0 / max(1, frames)))
    print("平均 rms        %.5f" % (sum(rms_list) / len(rms_list)))
    print("CPU 时间        %.2f 秒（墙钟 %.1f 秒）→ 占用 %.1f%%" % (cpu, wall, cpu * 100.0 / wall))
    print("峰值内存        %.1f MB" % peak_mb)
    print("网络请求        0（这段代码里根本没有网络调用）")
    print("token 消耗      0")


if __name__ == "__main__":
    main()
