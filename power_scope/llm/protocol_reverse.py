"""protocol_reverse.py — 串口未知协议帧结构启发式逆向。

对一批候选帧做纯启发式推断（无网络、无硬件、可完全单测）：
  - 帧头(SOF): 最长公共前缀 / 最常见首字节
  - 长度域: 找到某偏移的字节值与帧长呈固定关系(总长或载荷长)
  - 校验: 末 1~2 字节是否 = CRC16-Modbus / 累加和 / 异或(覆盖多种范围)
  - 字段稳定性: 各偏移是恒定还是变化(定位状态位/计数器/数据区)

推断结果可用 build_llm_prompt() 打包交 LLM 做结构化解释与命名。
"""
from __future__ import annotations
from collections import Counter


# ────────────────────────────────────────────────────────────────
# 校验算法（纯 python，避免 dll 依赖）
# ────────────────────────────────────────────────────────────────

def crc16_modbus(data: bytes) -> int:
    """CRC16-Modbus (poly 0xA001, init 0xFFFF)。返回 16bit 值(低字节在前的整数)。"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def _sum8(data: bytes) -> int:
    return sum(data) & 0xFF


def _xor8(data: bytes) -> int:
    x = 0
    for b in data:
        x ^= b
    return x & 0xFF


# ────────────────────────────────────────────────────────────────
# 流切分
# ────────────────────────────────────────────────────────────────

def split_stream(data: bytes, sof: bytes) -> list:
    """按帧头 sof 把连续字节流切成候选帧（不含尾部残段）。"""
    if not sof:
        return [data] if data else []
    frames = []
    i = data.find(sof)
    while i != -1:
        j = data.find(sof, i + len(sof))
        if j == -1:
            frames.append(data[i:])
            break
        frames.append(data[i:j])
        i = j
    return frames


# ────────────────────────────────────────────────────────────────
# 各维度推断
# ────────────────────────────────────────────────────────────────

def detect_header(frames: list) -> dict:
    """最长公共前缀 + 首字节众数。"""
    if not frames:
        return {"sof": b"", "confidence": 0.0}
    # 最长公共前缀
    prefix = frames[0]
    for f in frames[1:]:
        n = min(len(prefix), len(f))
        k = 0
        while k < n and prefix[k] == f[k]:
            k += 1
        prefix = prefix[:k]
        if not prefix:
            break
    if prefix:
        return {"sof": bytes(prefix), "confidence": 1.0}
    # 退化到首字节众数
    first = Counter(f[0] for f in frames if f)
    byte, cnt = first.most_common(1)[0]
    return {"sof": bytes([byte]), "confidence": cnt / len(frames)}


def detect_length_field(frames: list, max_offset: int = 4) -> dict:
    """在小偏移里找 frame[off] 与帧长呈固定差 k 的长度域。"""
    best = None
    valid = [f for f in frames if len(f) >= 2]
    if len(valid) < 2:
        return {"found": False}
    for off in range(max_offset):
        deltas = []
        ok = True
        for f in valid:
            if off >= len(f):
                ok = False
                break
            deltas.append(len(f) - f[off])
        if not ok:
            continue
        if len(set(deltas)) == 1:  # 固定关系 len = field + k
            k = deltas[0]
            best = {"found": True, "offset": off, "delta_to_total_len": k}
            break
    return best or {"found": False}


def detect_checksum(frames: list) -> dict:
    """检测末尾校验：CRC16(LE/BE) 或 单字节 sum/xor，覆盖 [start:-clen] 多种范围。"""
    valid = [f for f in frames if len(f) >= 3]
    if len(valid) < 2:
        return {"found": False}

    # 2 字节 CRC16-Modbus，数据范围从 start 到倒数第 2 字节
    for start in (0, 1):
        le = be = 0
        for f in valid:
            calc = crc16_modbus(f[start:-2])
            got_le = f[-2] | (f[-1] << 8)
            got_be = (f[-2] << 8) | f[-1]
            le += (calc == got_le)
            be += (calc == got_be)
        if le == len(valid):
            return {"found": True, "type": "crc16_modbus", "endian": "little",
                    "data_start": start, "check_len": 2}
        if be == len(valid):
            return {"found": True, "type": "crc16_modbus", "endian": "big",
                    "data_start": start, "check_len": 2}

    # 单字节 sum / xor
    for start in (0, 1):
        s = x = 0
        for f in valid:
            s += (_sum8(f[start:-1]) == f[-1])
            x += (_xor8(f[start:-1]) == f[-1])
        if s == len(valid):
            return {"found": True, "type": "sum8", "data_start": start, "check_len": 1}
        if x == len(valid):
            return {"found": True, "type": "xor8", "data_start": start, "check_len": 1}

    return {"found": False}


def field_stability(frames: list) -> list:
    """返回按偏移的稳定性：每个偏移是 'const'(值恒定) 还是 'var'(变化)。"""
    if not frames:
        return []
    min_len = min(len(f) for f in frames)
    out = []
    for off in range(min_len):
        vals = {f[off] for f in frames}
        out.append({"offset": off, "kind": "const" if len(vals) == 1 else "var",
                    "value": next(iter(vals)) if len(vals) == 1 else None})
    return out


def analyze_frames(frames: list) -> dict:
    """综合推断一批候选帧的结构。"""
    frames = [bytes(f) for f in frames if f]
    header = detect_header(frames)
    length = detect_length_field(frames)
    checksum = detect_checksum(frames)
    stability = field_stability(frames)
    lengths = sorted({len(f) for f in frames})
    return {
        "frame_count": len(frames),
        "lengths": lengths,
        "fixed_length": len(lengths) == 1,
        "header": header,
        "length_field": length,
        "checksum": checksum,
        "stability": stability,
    }


def summarize(analysis: dict) -> str:
    """把推断结果转成人类可读摘要。"""
    h = analysis["header"]
    lines = [
        f"候选帧数: {analysis['frame_count']}，帧长: {analysis['lengths']}"
        + ("（定长）" if analysis["fixed_length"] else "（变长）"),
        f"帧头 SOF: {h['sof'].hex(' ') or '(无)'} (置信 {h['confidence']:.0%})",
    ]
    lf = analysis["length_field"]
    if lf.get("found"):
        lines.append(f"长度域: 偏移 {lf['offset']}，总长 = 该字节 + {lf['delta_to_total_len']}")
    else:
        lines.append("长度域: 未识别")
    cs = analysis["checksum"]
    if cs.get("found"):
        endian = f"/{cs.get('endian')}" if cs.get("endian") else ""
        lines.append(f"校验: {cs['type']}{endian}，覆盖 [{cs['data_start']}:-{cs['check_len']}]")
    else:
        lines.append("校验: 未识别 (CRC16/sum/xor 均不匹配)")
    consts = [s["offset"] for s in analysis["stability"] if s["kind"] == "const"]
    lines.append(f"恒定字节偏移: {consts}")
    return "\n".join(lines)


def build_llm_prompt(analysis: dict, sample_hex: str = "") -> str:
    """把推断结果打包为让 LLM 做结构化解释/命名的提示词。"""
    return (
        "以下是对一段未知串口协议的启发式逆向结果，请据此推测各字段含义"
        "（帧头/地址/命令/长度/数据/校验），指出可能的协议族(如 Modbus-RTU)，"
        "并以表格给出 偏移-字段名-推测含义。若信息不足请说明还需采集什么。\n\n"
        f"{summarize(analysis)}\n\n"
        + (f"样例帧(hex): {sample_hex}\n" if sample_hex else "")
    )
