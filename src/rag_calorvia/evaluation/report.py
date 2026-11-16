"""Text reports: the mean of chosen metrics per question type or per evidence format, for several experiments."""
from collections import defaultdict


def evidence_format(question, registry):
    """The format of the documents holding the answer (grade-2 evidence): 'docx', 'xlsx', 'jpg'... or 'mixed'.

    'none' for out_of_corpus questions. Scans are reported as 'scan', not 'pdf': they behave like images.
    """
    formats = set()
    for evidence in question["evidence"]:
        if evidence["grade"] == 2:
            entry = registry.get(evidence["document"], {})
            formats.add("scan" if entry.get("source_type") == "scan" else entry.get("format", "?"))
    if not formats:
        return "none"
    return formats.pop() if len(formats) == 1 else "mixed"


def group_of(question, registry, by):
    return question["type"] if by == "type" else evidence_format(question, registry)


def summarize(scores_by_experiment, questions, registry, metric, by="type"):
    """{group: {experiment: (mean, n)}}, plus an 'all' group. A question without the metric is not counted
    (no recall for out_of_corpus, no trap_hit without traps): n says how many questions each mean is over."""
    table = defaultdict(lambda: defaultdict(list))
    for question in questions:
        group = group_of(question, registry, by)
        for experiment, scores in scores_by_experiment.items():
            value = scores.get(question["id"], {}).get(metric)
            if value is not None:
                table[group][experiment].append(value)
                table["all"][experiment].append(value)
    return {
        group: {experiment: (sum(values) / len(values), len(values)) for experiment, values in row.items()}
        for group, row in table.items()
    }


def format_table(summary, experiments, metric, by):
    """The summary as aligned text, groups sorted, 'all' last."""
    width = max(12, *(len(e) for e in experiments))
    lines = [f"{metric} by {by}", f"{by:22}" + "".join(f"{e:>{width + 2}}" for e in experiments)]
    for group in sorted(g for g in summary if g != "all") + ["all"]:
        cells = []
        for experiment in experiments:
            mean, n = summary.get(group, {}).get(experiment, (None, 0))
            cells.append(f"{'–' if mean is None else f'{mean:.3f}'} ({n})".rjust(width + 2))
        lines.append(f"{group:22}" + "".join(cells))
    return "\n".join(lines)
