"""pyqtgraph 的统一配色与显示优化。"""

from ..theme import current_theme, get_theme


def style_plot(plot, theme_name=None):
    import pyqtgraph as pg

    theme = get_theme(theme_name or current_theme())
    plot.setBackground(theme["input_bg"])
    plot.showGrid(x=True, y=True, alpha=0.18)
    item = plot.getPlotItem()
    for name in ("left", "bottom"):
        axis = item.getAxis(name)
        axis.setPen(pg.mkPen(theme["border_strong"]))
        axis.setTextPen(pg.mkPen(theme["text_dim"]))
    legend = item.legend
    if legend is not None and hasattr(legend, "setLabelTextColor"):
        legend.setLabelTextColor(theme["text_dim"])


def optimize_curve(curve):
    curve.setClipToView(True)
    curve.setDownsampling(auto=True, method="peak")
