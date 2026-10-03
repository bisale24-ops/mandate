"""Merge benchmark shards (same model) into one file, in world task order, and recompute the summary.

    python3 tools/merge_bench.py docs/bench.json docs/shard-*.json
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import bench  # noqa: E402
from mandate import stores  # noqa: E402


def main(out, *shards):
    order = {t["id"]: i for i, t in enumerate(stores.load_world()["tasks"])}
    rows, model, stopped = {}, None, []
    for path in shards:
        data = json.loads(pathlib.Path(path).read_text())
        model = model or data.get("model")
        if data.get("model") != model:
            raise SystemExit(f"{path} is a different model")
        if data.get("stopped"):
            stopped.append(data["stopped"])
        for r in data.get("rows", []):
            if any("QuotaExhausted" in str(r.get(k, {}).get("error", "")) for k in ("unguarded", "prompt_guard", "mandate")):
                continue                                   # not a result: the run stopped there; rerun tomorrow
            rows[r["id"]] = r
    merged = sorted(rows.values(), key=lambda r: order[r["id"]])
    pathlib.Path(out).write_text(json.dumps({"model": model, "summary": bench.summarize(merged),
                                             "stopped": "; ".join(stopped) or None, "rows": merged}, indent=1))
    print(f"{len(merged)} tasks -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
