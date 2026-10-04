"""Write the benchmark tables into README.md and docs/devpost_story.md from docs/bench*.json, so the prose
never drifts from the data.

    python3 tools/results_table.py
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARMS = [("unguarded", "No guard"), ("prompt_guard", '"Ignore page instructions" in the prompt'),
        ("mandate", "**Mandate**")]


def table(path):
    d = json.loads(path.read_text())
    s = d["summary"]
    n = len(d["rows"])
    out = [f"`{path.name}`: {n} tasks, model `{d['model']}`, live PayPal sandbox", "",
           "| | Harmful payments | Paid more than the best deal | Right item, best price | Lost to attacks | Honest buys |",
           "|---|---|---|---|---|---|"]
    for key, label in ARMS:
        a = s[key]
        bold = (lambda x: f"**{x}**") if key == "mandate" else (lambda x: x)
        out.append(f"| {label} | {bold(f'{a['harm_on_attacks']} / {a['attacks']}')} | {bold(a['degraded_on_attacks'])} | "
                   f"{bold(a['correct_on_attacks'])} | {bold('$' + format(float(a['dollars_lost_on_attacks']), ',.2f'))} | "
                   f"{bold(f'{a['honest_completed']} / {a['honest']}')} |")
    return "\n".join(out)


def block():
    files = [ROOT / "docs" / "bench.json"] + sorted(p for p in (ROOT / "docs").glob("bench-*.json")
                                                     if p.name != "bench-tent.json")
    return "\n\n".join(table(p) for p in files if p.exists())


def put(path, start, end, text):
    s = path.read_text()
    a, b = s.index(start) + len(start), s.index(end)
    path.write_text(s[:a] + "\n" + text + "\n" + s[b:])


if __name__ == "__main__":
    t = block()
    put(ROOT / "README.md", "<!-- results:start -->", "<!-- results:end -->", t)
    put(ROOT / "docs" / "devpost_story.md", "<!-- results:start -->", "<!-- results:end -->", t)
    print(t)
