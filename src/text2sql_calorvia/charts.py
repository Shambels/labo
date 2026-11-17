"""Charts of query results (step 15): a PNG served by the endpoint, shown in the answer as a Markdown image.

The model names a result (q1, q2...) and its columns; the rows come from the agent's state, as for reconcile, so
the chart shows exactly what the query returned and nothing the privacy rule kept out. Open WebUI displays Markdown
images, so the answer carries ![title](http://…/charts/<id>.png): the link is added by the agent's finish node,
not written by the model.
"""
import uuid
from pathlib import Path

import matplotlib

matplotlib.use("Agg")   # no display: render to files
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from text2sql_calorvia.config import settings  # noqa: E402

KINDS = ("bar", "line", "pie")
MAX_POINTS = 60
PALETTE = ["#2563eb", "#f97316", "#16a34a", "#9333ea", "#dc2626", "#0891b2"]


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _french(value, _=None):
    """1234567.8 -> '1 234 568' (axis labels, in the language of the answers)."""
    return f"{value:,.0f}".replace(",", " ")


def make_chart(result: dict, kind: str, x: str, y: list[str], title: str, directory: Path | None = None) -> dict:
    """Draw columns `y` of a result against column `x`; returns {"id", "file", "title"} or raises ValueError."""
    if kind not in KINDS:
        raise ValueError(f"Type de graphique inconnu : {kind}. Types : {', '.join(KINDS)}.")
    lowered = [c.lower() for c in result["columns"]]
    missing = [c for c in [x, *y] if c.lower() not in lowered]
    if missing:
        raise ValueError(f"Colonne(s) absente(s) du résultat : {', '.join(missing)} "
                         f"(colonnes : {', '.join(result['columns'])}).")
    if kind == "pie" and len(y) != 1:
        raise ValueError("Un graphique en secteurs montre une seule colonne de valeurs.")
    rows = result["rows"]
    if not rows:
        raise ValueError("Le résultat est vide : rien à représenter.")
    if len(rows) > MAX_POINTS:
        raise ValueError(f"{len(rows)} lignes : trop pour un graphique lisible (au plus {MAX_POINTS}). "
                         "Agrégez ou limitez la requête.")
    xi, yis = lowered.index(x.lower()), [lowered.index(c.lower()) for c in y]
    labels = [str(r[xi]) for r in rows]
    series = [[_number(r[i]) for r in rows] for i in yis]
    if any(v is None for s in series for v in s):
        raise ValueError("Les colonnes de valeurs doivent être numériques et sans valeur vide.")

    fig, ax = plt.subplots(figsize=(9, 5), dpi=110)
    if kind == "pie":
        ax.pie(series[0], labels=labels, autopct="%1.1f %%", colors=PALETTE * 10, startangle=90,
               wedgeprops={"linewidth": 1, "edgecolor": "white"})
        ax.axis("equal")
    else:
        width = 0.8 / len(series)
        for n, (name, values) in enumerate(zip(y, series)):
            if kind == "bar":
                positions = [i + (n - (len(series) - 1) / 2) * width for i in range(len(labels))]
                ax.bar(positions, values, width=width, label=name, color=PALETTE[n % len(PALETTE)])
            else:
                ax.plot(range(len(labels)), values, marker="o", label=name, color=PALETTE[n % len(PALETTE)])
        ax.set_xticks(range(len(labels)), labels, rotation=45 if max(map(len, labels)) > 6 else 0, ha="right"
                      if max(map(len, labels)) > 6 else "center")
        ax.yaxis.set_major_formatter(FuncFormatter(_french))
        ax.grid(axis="y", alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_xlabel(x)
        if len(series) > 1:
            ax.legend(frameon=False)
    ax.set_title(title)
    fig.tight_layout()
    directory = directory or settings.charts_dir
    directory.mkdir(parents=True, exist_ok=True)
    chart_id = uuid.uuid4().hex[:16]
    path = directory / f"{chart_id}.png"
    fig.savefig(path)
    plt.close(fig)
    return {"id": chart_id, "file": str(path), "title": title}


def chart_url(chart_id: str) -> str:
    return f"{settings.agent_public_url.rstrip('/')}/charts/{chart_id}.png"
