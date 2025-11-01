# analyzer.py
import re
from typing import Dict, List, Any


def _normalize_results(raw: Dict[str, Any]):
    """Normalize different JSON test result formats into summary and failures list."""
    if isinstance(raw.get("stats"), dict):
        st = raw["stats"]
        expected = int(st.get("expected") or 0)
        unexpected = int(st.get("unexpected") or 0)
        total = expected + unexpected + int(st.get("flaky") or 0) + int(st.get("skipped") or 0)
        failures = []

        def walk(node):
            for spec in (node.get("specs") or []):
                ok = spec.get("ok")
                if ok is False:
                    fail = {"title": spec.get("title"), "file": spec.get("file"), "line": spec.get("line")}
                    msgs = []
                    for t in (spec.get("tests") or []):
                        for r in (t.get("results") or []):
                            if (r.get("status") or "").lower() == "failed":
                                msg = None
                                if isinstance(r.get("error"), dict):
                                    msg = r["error"].get("message") or r["error"].get("stack")
                                if not msg and r.get("errors"):
                                    msg = r["errors"][0].get("message")
                                if msg:
                                    msgs.append(msg.strip())
                    if msgs:
                        fail["messages"] = msgs
                    failures.append(fail)
            for s in (node.get("suites") or []):
                walk(s)

        for top in (raw.get("suites") or []):
            walk(top)
        return {"total": total, "passed": expected, "failed": unexpected}, failures

    raise KeyError("Could not parse test results; missing `stats` section")


def _signature(text: str) -> str:
    t = re.sub(r"/__w/[^\\s]+", "<WORKDIR>", text or "")
    t = re.sub(r":\\d+", ":", t)
    t = t.lower()
    keywords = ["timeout", "tocontaintext", "element(s) not found",
                "waiting for locator", "click", "authentication", "401"]
    for k in keywords:
        t = t.replace(k, f"[{k}]")
    return t.strip() or "[unknown]"


def _cluster_failures(failures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for f in failures:
        msgs = f.get("messages", []) if isinstance(f, dict) else [str(f)]
        base = "\n".join(m for m in msgs if m) or f.get("title", "unknown")
        sig = _signature(base)
        g = groups.setdefault(sig, {"sig": sig, "count": 0, "examples": []})
        g["count"] += 1
        if isinstance(f, dict):
            g["examples"].append({
                "file": f.get("file", "?"),
                "line": f.get("line", "?"),
                "title": f.get("title", "(no title)"),
            })
    return sorted(groups.values(), key=lambda x: -x["count"])


def _format_simple(summary: Dict[str, int], clusters: List[Dict[str, Any]], max_examples: int = 2) -> str:
    lines = []
    total, passed, failed = summary.get("total", 0), summary.get("passed", 0), summary.get("failed", 0)
    lines.append(f"✅ {passed}/{total} passed • {failed} failed\n")

    if clusters:
        lines.append("Top issues")
        for i, c in enumerate(clusters, 1):
            head = c["sig"][:100]
            lines.append(f"{i}) {head} (x{c['count']})")
            for ex in c["examples"][:max_examples]:
                lines.append(f"   - {ex['file']}:{ex['line']}  {ex['title']}")
    return "\n".join(lines).strip()
