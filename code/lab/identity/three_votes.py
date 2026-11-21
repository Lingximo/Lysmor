"""三票制：人脸 + 声纹 + 在场 → 决定"现在是谁、用什么态度"。

部署者的定调（§74.6）：
    两票以上 → 确认是你（叫你、撒娇、说私事）
    一票     → 不确定：客气但疏远，不主动
    零票     → 当陌生人在场处理

    宁可冷淡，不可谄媚。

设计要点（部署者要求：限制不要写死）
    · 票的来源可插拔：face / voice / presence 各自给 (who, score)
    · 阈值从 config 读，不写死在代码里
    · 多人登记时按"谁得票多"决定，不是全局一个人
    · 输出只有"判断"，不做任何动作；动作由上层决定

用法：
    from three_votes import VoteInput, decide
    r = decide(VoteInput(face=("dad",0.62), voice=("dad",0.81), presence=True))
    r.person, r.votes, r.attitude   # -> "dad", 3, "warm"
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 默认阈值（可被 config 覆盖）
DEFAULTS = {
    "face_known": 0.45,     # 1:N 人脸相似度
    "voice_known": 0.75,    # 声纹余弦
    "need_margin": 0.08,    # 与第二名的差距，太近算不确定
}


@dataclass
class VoteInput:
    face: tuple | None = None      # ("dad", score) 或 None
    voice: tuple | None = None     # ("dad", 0.81) 或 None
    presence: bool = False         # 手机蓝牙在附近 / 键鼠在用
    presence_person: str = "dad"   # 在场默认归给谁（可配）


@dataclass
class Decision:
    person: str | None = None
    votes: int = 0
    attitude: str = "stranger"     # warm / polite / stranger
    detail: dict = field(default_factory=dict)


def decide(inp: VoteInput, cfg: dict | None = None) -> Decision:
    cfg = {**DEFAULTS, **(cfg or {})}
    ballots: dict[str, int] = {}
    detail: dict = {}

    if inp.face:
        who, score = inp.face
        ok = score >= cfg["face_known"]
        detail["face"] = {"who": who, "score": round(float(score), 3), "ok": ok}
        if ok:
            ballots[who] = ballots.get(who, 0) + 1

    if inp.voice:
        who, score = inp.voice
        ok = score >= cfg["voice_known"]
        detail["voice"] = {"who": who, "score": round(float(score), 3), "ok": ok}
        if ok:
            ballots[who] = ballots.get(who, 0) + 1

    if inp.presence:
        ballots[inp.presence_person] = ballots.get(inp.presence_person, 0) + 1
        detail["presence"] = True

    if not ballots:
        return Decision(None, 0, "stranger", detail)

    person, votes = max(ballots.items(), key=lambda kv: kv[1])
    # 平票 → 不算确认，按一票处理
    tied = sum(1 for v in ballots.values() if v == votes) > 1
    detail["ballots"] = ballots
    detail["tied"] = tied

    if votes >= 2 and not tied:
        attitude = "warm"
        person_out = person
    elif votes >= 1:
        attitude = "polite"
        person_out = person if votes >= 1 and not tied else None
    else:
        attitude = "stranger"
        person_out = None
    return Decision(person_out, votes, attitude, detail)


def attitude_policy(attitude: str, role: str = "family") -> dict:
    """态度 → 行为约束（给对话层用，不在这里执行）。"""
    if attitude == "warm":
        return {
            "call_dad": role == "owner",
            "affection": role == "owner",
            "private_memory": role == "owner",
            "proactive": True,
        }
    if attitude == "polite":
        return {
            "call_dad": False,
            "affection": False,
            "private_memory": False,
            "proactive": False,
        }
    return {
        "call_dad": False,
        "affection": False,
        "private_memory": False,
        "proactive": False,
        "stranger_mode": True,
    }


if __name__ == "__main__":
    cases = [
        ("三票全中", VoteInput(("dad", 0.62), ("dad", 0.81), True)),
        ("两票（脸+声）", VoteInput(("dad", 0.62), ("dad", 0.81), False)),
        ("只有声纹", VoteInput(None, ("dad", 0.81), False)),
        ("只有人脸", VoteInput(("dad", 0.50), None, False)),
        ("人脸不确定", VoteInput(("dad", 0.30), None, False)),
        ("两个人各一票", VoteInput(("mom", 0.55), ("dad", 0.80), False)),
        ("没人", VoteInput(None, None, False)),
    ]
    for name, inp in cases:
        d = decide(inp)
        print("%-14s person=%-5s votes=%d attitude=%-8s %s" %
              (name, d.person, d.votes, d.attitude, d.detail.get("ballots", {})))
