"""debug_report.py — 一键调试报告生成（P1-11 的纯逻辑层）

把「状态捕获快照」（PowerMainWindow._snapshot_payload）、调参指标、写入审计
渲染成人类可读的 Markdown 与自包含 HTML（内联 CSS，无外部资源，可直接
贴邮件/微信群或归档）。

输入是普通 dict（report sections 由调用方组装），本模块不 import Qt，
可独立单测；渲染失败时降级为纯文本而不是抛异常中断现场排障。
"""
from __future__ import annotations

import datetime as _dt
import html
from dataclasses import dataclass, field


@dataclass
class ReportInput:
    """报告的全部输入。字段都是可 JSON 化的普通数据。"""

    generated_at: str = ""
    device: str = ""
    connection: str = ""
    values: dict = field(default_factory=dict)
    alarms: list[str] = field(default_factory=list)
    msg_latency: dict = field(default_factory=dict)
    wave_diagnostics: dict = field(default_factory=dict)
    tuning_metrics: dict = field(default_factory=dict)
    tuning_params: dict = field(default_factory=dict)
    audit_records: list[dict] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = _dt.datetime.now().astimezone().isoformat(
                timespec="seconds")


def _fmt_ts(stamp: float) -> str:
    try:
        return _dt.datetime.fromtimestamp(float(stamp)).strftime("%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(stamp)


def _fmt_value(value) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def render_markdown(report: ReportInput) -> str:
    """渲染 Markdown 报告。"""
    lines: list[str] = []
    lines.append("# PowerScope 调试报告")
    lines.append("")
    lines.append(f"- 生成时间: {report.generated_at}")
    lines.append(f"- 设备: {report.device or '—'}")
    lines.append(f"- 连接: {report.connection or '—'}")
    lines.append("")

    lines.append("## 运行状态")
    lines.append("")
    if report.values:
        lines.append("| 变量 | 值 |")
        lines.append("|---|---|")
        for key in sorted(report.values):
            lines.append(f"| {key} | {_fmt_value(report.values[key])} |")
    else:
        lines.append("（无遥测数据 — 未连接或轮询未启动）")
    lines.append("")

    lines.append("## 活动告警")
    lines.append("")
    if report.alarms:
        for alarm in report.alarms:
            lines.append(f"- {alarm}")
    else:
        lines.append("无活动告警")
    lines.append("")

    if report.msg_latency:
        lines.append("## MSG 轮询延迟")
        lines.append("")
        for key in sorted(report.msg_latency):
            lines.append(f"- {key}: {_fmt_value(report.msg_latency[key])}")
        lines.append("")

    if report.tuning_params or report.tuning_metrics:
        lines.append("## 调参")
        lines.append("")
        if report.tuning_params:
            lines.append("- 当前参数: " + ", ".join(
                f"{k}={_fmt_value(v)}" for k, v in report.tuning_params.items()))
        if report.tuning_metrics:
            for key in sorted(report.tuning_metrics):
                lines.append(
                    f"- {key}: {_fmt_value(report.tuning_metrics[key])}")
        lines.append("")

    if report.wave_diagnostics:
        lines.append("## 录波诊断")
        lines.append("")
        for key in sorted(report.wave_diagnostics):
            lines.append(f"- {key}: {_fmt_value(report.wave_diagnostics[key])}")
        lines.append("")

    lines.append("## 写入审计（最近）")
    lines.append("")
    if report.audit_records:
        lines.append("| 时间 | 变量 | 旧值 | 新值 | 来源 | 备注 |")
        lines.append("|---|---|---|---|---|---|")
        for rec in list(reversed(report.audit_records))[-20:]:
            lines.append(
                f"| {_fmt_ts(rec.get('timestamp', 0))} | {rec.get('var', '')} | "
                f"{_fmt_value(rec.get('old_value'))} | "
                f"{_fmt_value(rec.get('new_value'))} | {rec.get('source', '')} | "
                f"{rec.get('note', '')} |")
    else:
        lines.append("（无写入记录）")
    lines.append("")

    if report.notes.strip():
        lines.append("## 备注")
        lines.append("")
        lines.append(report.notes.strip())
        lines.append("")
    return "\n".join(lines)


_CSS = """
body { font-family: 'Microsoft YaHei', 'Segoe UI', Arial, sans-serif;
       background:#171c28; color:#dce0e8; margin:0; padding:32px; }
main { max-width: 880px; margin: 0 auto; }
h1 { font-size: 22px; border-bottom: 1px solid #3a4157; padding-bottom: 10px; }
h2 { font-size: 16px; color:#959aa8; margin-top: 28px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #3a4157; padding: 6px 10px; text-align: left; }
th { background:#20253a; }
tr:nth-child(even) td { background:#1b2131; }
.meta { color:#959aa8; font-size: 13px; line-height: 1.8; }
.alarm { color:#e74c3c; } .ok { color:#2ecc71; }
code { font-family: Consolas, monospace; }
"""


def render_html(report: ReportInput) -> str:
    """渲染自包含 HTML 报告（内联 CSS，无外部依赖）。"""
    esc = html.escape

    def _rows(data: dict) -> str:
        if not data:
            return "<p class='meta'>（无数据）</p>"
        body = "".join(
            f"<tr><td>{esc(str(k))}</td><td><code>{esc(_fmt_value(v))}</code></td></tr>"
            for k, v in sorted(data.items()))
        return ("<table><tr><th>变量</th><th>值</th></tr>"
                + body + "</table>")

    alarms = "".join(f"<li class='alarm'>{esc(a)}</li>" for a in report.alarms)
    alarm_block = (f"<ul>{alarms}</ul>" if alarms
                   else "<p class='ok'>无活动告警</p>")

    audit_rows = ""
    for rec in list(reversed(report.audit_records))[-20:]:
        audit_rows += (
            f"<tr><td>{esc(_fmt_ts(rec.get('timestamp', 0)))}</td>"
            f"<td>{esc(str(rec.get('var', '')))}</td>"
            f"<td>{esc(_fmt_value(rec.get('old_value')))}</td>"
            f"<td>{esc(_fmt_value(rec.get('new_value')))}</td>"
            f"<td>{esc(str(rec.get('source', '')))}</td>"
            f"<td>{esc(str(rec.get('note', '')))}</td></tr>")
    audit_block = (
        ("<table><tr><th>时间</th><th>变量</th><th>旧值</th><th>新值</th>"
         "<th>来源</th><th>备注</th></tr>" + audit_rows + "</table>")
        if audit_rows else "<p class='meta'>（无写入记录）</p>")

    tuning_block = ""
    if report.tuning_params or report.tuning_metrics:
        params = ", ".join(f"{k}={_fmt_value(v)}"
                           for k, v in report.tuning_params.items())
        metrics = "".join(
            f"<li>{esc(str(k))}: <code>{esc(_fmt_value(v))}</code></li>"
            for k, v in sorted(report.tuning_metrics.items()))
        tuning_block = (
            f"<h2>调参</h2><p>当前参数: <code>{esc(params or '—')}</code></p>"
            f"<ul>{metrics}</ul>")

    notes_block = (f"<h2>备注</h2><p>{esc(report.notes.strip())}</p>"
                   if report.notes.strip() else "")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>PowerScope 调试报告 — {esc(report.generated_at)}</title>
<style>{_CSS}</style></head><body><main>
<h1>PowerScope 调试报告</h1>
<p class="meta">生成时间: {esc(report.generated_at)}<br>
设备: {esc(report.device or '—')}<br>连接: {esc(report.connection or '—')}</p>
<h2>运行状态</h2>{_rows(report.values)}
<h2>活动告警</h2>{alarm_block}
{tuning_block}
<h2>写入审计（最近）</h2>{audit_block}
{notes_block}
</main></body></html>"""


def report_from_snapshot(payload: dict, tuning_metrics: dict | None = None,
                         tuning_params: dict | None = None,
                         audit_records: list[dict] | None = None,
                         notes: str = "") -> ReportInput:
    """从 PowerMainWindow._snapshot_payload() 的 dict 组装报告输入。"""
    connection = payload.get("connection", {}) or {}
    conn_text = (f"{connection.get('state', '')} {connection.get('info', '')}"
                 ).strip()
    return ReportInput(
        device=str(payload.get("device_profile", "")),
        connection=conn_text,
        values=dict(payload.get("values", {}) or {}),
        alarms=[str(a) for a in payload.get("active_alarms", []) or []],
        msg_latency=dict(payload.get("msg_latency", {}) or {}),
        wave_diagnostics=dict(payload.get("last_wave_recorder", {}) or {}),
        tuning_metrics=dict(tuning_metrics or {}),
        tuning_params=dict(tuning_params or {}),
        audit_records=list(audit_records or []),
        notes=notes,
    )
