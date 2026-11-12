"""Composants d'interface partagés du tableau de bord (style homogène).

En-têtes de page, cartes de chiffres clés, badges de verdict, états vides et
graphiques Altair communs (éventail de projection, barres d'intervalle). Les
couleurs viennent du thème (``.streamlit/config.toml``) : aucun code couleur en
dur, sauf pour les niveaux sémantiques (vert / orange / rouge).
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

VERDICT_COLORS = {
    # fiabilité
    "robuste": "green", "acceptable": "orange", "fragile": "red",
    # surperformance
    "démontrée": "green", "possible": "orange", "non démontrée": "gray",
    # protection
    "forte": "green", "moyenne": "orange", "faible": "red",
    # adéquation au profil
    "adapté": "green", "adapté avec réserves": "orange", "peu adapté": "red",
    # statut du rapport
    "OK": "green", "OK_WITH_WARNINGS": "orange", "CRITICAL": "red",
    "référence": "blue", "n/a": "gray",
}
SEMANTIC_HEX = {"green": "#16a34a", "orange": "#f59e0b", "red": "#dc2626", "gray": "#64748b", "blue": "#2563eb"}
STATUS_ICONS = {"ok": ":material/check_circle:", "reserve": ":material/warning:", "ko": ":material/cancel:"}


def eur(value: float | None, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:,.{digits}f} €".replace(",", " ")


def pct(value: float | None, digits: int = 0, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:+.{digits}%}" if signed else f"{value:.{digits}%}"


def page_header(title: str, subtitle: str | None = None, *, icon: str | None = None) -> None:
    """Titre de page + sous-titre discret."""
    st.title(f"{icon} {title}" if icon else title, anchor=False)
    if subtitle:
        st.caption(subtitle)


def section(title: str, caption: str | None = None) -> None:
    st.subheader(title, anchor=False, divider="gray")
    if caption:
        st.caption(caption)


def badge(text: str, *, icon: str | None = None, color: str | None = None) -> None:
    st.badge(text, icon=icon, color=color or VERDICT_COLORS.get(text, "gray"))  # type: ignore[arg-type]


def badges(items: list[tuple[str, str]]) -> None:
    """Rangée de badges ``(libellé, verdict)``."""
    with st.container(horizontal=True, gap="small"):
        for label, verdict in items:
            st.badge(f"{label} : {verdict}", color=VERDICT_COLORS.get(verdict, "gray"))  # type: ignore[arg-type]


def kpis(items: list[dict]) -> None:
    """Cartes de chiffres clés ``{"label", "value", "help"?, "delta"?, "delta_color"?}``."""
    with st.container(horizontal=True, gap="small"):
        for item in items:
            st.metric(item["label"], item["value"], delta=item.get("delta"), help=item.get("help"), border=True,
                      delta_color=item.get("delta_color", "normal"), delta_arrow=item.get("delta_arrow", "auto"))


def empty_state(message: str, command: str | None = None, *, icon: str = ":material/info:") -> None:
    with st.container(border=True):
        st.markdown(f"{icon} {message}")
        if command:
            st.code(command, language="bash")


def check_list(checks: list[dict]) -> None:
    """Liste de contrôles ``{"niveau": ok|reserve|ko, "message"}``."""
    for check in checks:
        st.markdown(f"{STATUS_ICONS.get(check['niveau'], '')} {check['message']}")


def disclaimer(text: str = "Ordres de grandeur éducatifs, pas des conseils en investissement. Aucun ordre n'est "
                           "passé par le laboratoire.") -> None:
    st.caption(f":material/shield: {text}")


# --------------------------------------------------------------------------- #
# Graphiques
# --------------------------------------------------------------------------- #
def euro_axis(title: str | None = None) -> alt.Axis:
    return alt.Axis(title=title, format="~s", labelExpr="replace(datum.label, 'k', ' k') + ' €'")


def fan_chart(fan: dict, *, real: bool = True, goal: float | None = None, height: int = 320) -> alt.LayerChart:
    """Éventail de projection : bandes 80 % et 50 %, médiane, versements cumulés."""
    values = fan["real" if real else "nominal"]
    years = [m / 12 for m in fan["months"]]
    frame = pd.DataFrame({"année": years, **values,
                          "versé": fan["contributed_real" if real else "contributed"]})
    base = alt.Chart(frame).encode(x=alt.X("année:Q", title="années", axis=alt.Axis(tickMinStep=1),
                                           scale=alt.Scale(domain=[0, years[-1]], nice=False)))
    layers = [
        base.mark_area(opacity=0.18).encode(y=alt.Y("p10:Q", axis=euro_axis()), y2="p90:Q"),
        base.mark_area(opacity=0.30).encode(y="p25:Q", y2="p75:Q"),
        base.mark_line(strokeWidth=3).encode(y="p50:Q", tooltip=[
            alt.Tooltip("année:Q", format=".0f"), alt.Tooltip("p10:Q", title="défavorable", format=",.0f"),
            alt.Tooltip("p50:Q", title="médiane", format=",.0f"), alt.Tooltip("p90:Q", title="favorable", format=",.0f"),
            alt.Tooltip("versé:Q", format=",.0f")]),
        base.mark_line(strokeDash=[6, 4], color="#64748b").encode(y="versé:Q"),
    ]
    if goal:
        layers.append(alt.Chart(pd.DataFrame({"objectif": [goal]})).mark_rule(strokeDash=[2, 3], color="#dc2626")
                      .encode(y="objectif:Q"))
    return alt.layer(*layers).properties(height=height)


def range_chart(frame: pd.DataFrame, *, label: str, low: str, mid: str, high: str, color: str | None = None,
                x_title: str | None = None, reference: float | None = None, euros: bool = True,
                height: int | None = None) -> alt.LayerChart:
    """Barres d'intervalle horizontales (bas-haut) avec un point au milieu."""
    axis = euro_axis(x_title) if euros else alt.Axis(title=x_title, format="%")
    order = frame[label].tolist()
    base = alt.Chart(frame).encode(y=alt.Y(f"{label}:N", title=None, sort=order, axis=alt.Axis(labelLimit=320)))
    if color:
        values = list(dict.fromkeys(frame[color]))
        semantic = {v: SEMANTIC_HEX[VERDICT_COLORS[v]] for v in values if VERDICT_COLORS.get(v) in SEMANTIC_HEX}
        scale = alt.Scale(domain=list(semantic), range=list(semantic.values())) if len(semantic) == len(values) \
            else alt.Undefined
        color_enc = alt.Color(f"{color}:N", title=None, scale=scale, legend=alt.Legend(orient="bottom"))
    else:
        color_enc = alt.value("#2563eb")
    tooltip = [c for c in frame.columns if c != "_"]
    layers = [base.mark_rule(strokeWidth=8, opacity=0.35, strokeCap="round").encode(
                  x=alt.X(f"{low}:Q", axis=axis), x2=f"{high}:Q", color=color_enc),
              base.mark_point(filled=True, size=140, opacity=1).encode(x=f"{mid}:Q", color=color_enc,
                                                                        tooltip=tooltip)]
    if reference is not None:
        layers.append(alt.Chart(pd.DataFrame({"x": [reference]})).mark_rule(strokeDash=[4, 4], color="#64748b")
                      .encode(x="x:Q"))
    chart = alt.layer(*layers)
    return chart.properties(height=height or max(140, 46 * len(frame)))


def line_chart(frame: pd.DataFrame, *, x: str, y: str, color: str | None = None, y_format: str = ",.0f",
               percent: bool = False, height: int = 300, euros: bool = False) -> alt.Chart:
    axis = alt.Axis(format="%") if percent else (euro_axis() if euros else alt.Axis(format="~s"))
    enc = {"x": alt.X(f"{x}:T", title=None), "y": alt.Y(f"{y}:Q", title=None, axis=axis),
           "tooltip": [alt.Tooltip(f"{x}:T"), alt.Tooltip(f"{y}:Q", format=".1%" if percent else y_format)]}
    if color:
        enc["color"] = alt.Color(f"{color}:N", title=None, legend=alt.Legend(orient="bottom"))
        enc["tooltip"].insert(1, alt.Tooltip(f"{color}:N"))
    return alt.Chart(frame).mark_line(strokeWidth=2).encode(**enc).properties(height=height)
