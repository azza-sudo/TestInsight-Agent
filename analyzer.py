# analyzer.py
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import Counter, defaultdict

from utils import AppConfig, OpenAITextClient


class Analyzer:
    """
    Parse Playwright JSON (the schema you sent), extract stats & failures,
    detect failure patterns, and ask OpenAI for:
      - executive summary (for PMs)
      - prioritized next actions (for the team)
    """

    def __init__(self, cfg: Optional[AppConfig] = None, llm: Optional[OpenAITextClient] = None):
        self.cfg = cfg or AppConfig()
        self.llm = llm or OpenAITextClient(self.cfg)

    # ----------------- Public API -----------------
    def analyze_file(self, json_path: str | Path) -> Dict[str, Any]:
        data = self._load(json_path)

        stats = self._stats_from_payload(data)
        failures = self._collect_failures(data)  # list of dicts
        pattern_report = self._summarize_patterns(failures)
        ci_meta = self._extract_ci_meta(data)

        summary_prompt = self._prompt_summary(stats, failures, pattern_report, ci_meta)
        next_actions_prompt = self._prompt_next_actions(stats, failures, pattern_report, ci_meta)

        summary = self.llm.generate(summary_prompt)
        next_actions = self.llm.generate(next_actions_prompt)

        return {
            "stats": stats,
            "failures": failures,
            "patterns": pattern_report,
            "ci": ci_meta,
            "summary": summary,
            "next_actions": next_actions,
        }

    # ----------------- Parsing -----------------
    def _load(self, path: str | Path) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {p}")
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _stats_from_payload(self, data: Dict[str, Any]) -> Dict[str, int]:
        """
        Playwright JSON (reporter 'json') top-level has:
        stats: { expected, unexpected, skipped, flaky, ... }
        We'll compute passed conservatively as expected - skipped.
        """
        s = data.get("stats", {}) or {}
        expected = int(s.get("expected", 0))
        skipped = int(s.get("skipped", 0))
        unexpected = int(s.get("unexpected", 0))
        flaky = int(s.get("flaky", 0))
        # 'expected' counts all expected outcomes (passed + expected skips/etc).
        passed = max(expected - skipped, 0)
        total = expected + unexpected + skipped  # close-enough view
        return {
            "total": total,
            "passed": passed,
            "failed": unexpected,  # failures ~ unexpected
            "skipped": skipped,
            "flaky": flaky,
        }

    def _collect_failures(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Walk suites -> nested suites -> specs -> tests -> results
        Grab any result with status == 'failed'
        """
        failures: List[Dict[str, Any]] = []

        def walk_suites(suites: List[Dict[str, Any]], file_hint: Optional[str] = None):
            for suite in suites or []:
                file_here = suite.get("file") or file_hint
                # specs at this level
                for spec in suite.get("specs", []):
                    spec_file = spec.get("file") or file_here
                    spec_title = spec.get("title")
                    for t in spec.get("tests", []):
                        for res in t.get("results", []):
                            if (res.get("status") or "").lower() == "failed":
                                err = res.get("error") or {}
                                # The schema shows both 'error' and 'errors' lists.
                                errors_list = res.get("errors") or []
                                first_err_msg = (err.get("message") or
                                                 (errors_list[0].get("message") if errors_list else ""))

                                failures.append({
                                    "suiteFile": file_here,
                                    "specFile": spec_file,
                                    "title": spec_title,
                                    "workerIndex": res.get("workerIndex"),
                                    "retry": res.get("retry"),
                                    "duration_ms": res.get("duration"),
                                    "message": _compact(first_err_msg),
                                    "shortSignature": self._signature(first_err_msg),
                                    "attachments": [
                                        a.get("path") for a in (res.get("attachments") or []) if a.get("path")
                                    ],
                                    "errorLocation": res.get("errorLocation") or err.get("location"),
                                })

                # nested suites
                if suite.get("suites"):
                    walk_suites(suite["suites"], file_here)

        walk_suites(data.get("suites", []))
        return failures

    # --------------- Pattern grouping ---------------
    def _signature(self, msg: str) -> str:
        """
        Produce a compact 'signature' string to cluster similar errors.
        Simple rules based on your sample:
          - Normalize locator + selector substrings
          - Map common Playwright timeouts & not-found expectations
        """
        m = msg or ""
        m_low = m.lower()

        if "locator('.alert-danger')" in m or ".alert-danger" in m_low:
            return "validation-banner-not-found (.alert-danger)"
        if "[data-testid=\"profile-menu\"]" in m or "profile-menu" in m_low:
            return "logout-menu-timeout ([data-testid=profile-menu])"
        if "toContainText" in m:
            return "expect.toContainText timeout"
        if "timeout" in m_low and "click" in m_low:
            return "page.click timeout"
        return "other"

    def _summarize_patterns(self, failures: List[Dict[str, Any]]) -> Dict[str, Any]:
        buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for f in failures:
            buckets[f["shortSignature"]].append(f)

        counts = {k: len(v) for k, v in buckets.items()}
        top = sorted(counts.items(), key=lambda x: x[1], reverse=True)

        sample_msgs = {k: [x["message"] for x in v[:2]] for k, v in buckets.items()}
        return {
            "counts": counts,
            "top": top,
            "samples": sample_msgs,
        }

    # --------------- CI/links ----------------
    def _extract_ci_meta(self, data: Dict[str, Any]) -> Dict[str, Any]:
        cfg = data.get("config", {}) or {}
        meta = (cfg.get("metadata") or {}).get("ci") or {}
        return {
            "commitHash": meta.get("commitHash"),
            "commitHref": meta.get("commitHref"),
            "buildHref": meta.get("buildHref"),
            "project": (cfg.get("projects") or [{}])[0].get("name"),
            "runnerVersion": cfg.get("version"),
            "startTime": (data.get("stats") or {}).get("startTime"),
            "duration_ms": (data.get("stats") or {}).get("duration"),
        }

    # --------------- Prompts ----------------
    def _prompt_summary(
        self,
        stats: Dict[str, int],
        failures: List[Dict[str, Any]],
        patterns: Dict[str, Any],
        ci: Dict[str, Any],
    ) -> str:
        # keep payloads compact
        failures_view = [
            {
                "title": f["title"],
                "specFile": f["specFile"],
                "retry": f["retry"],
                "message": f["message"][:500],
                "signature": f["shortSignature"],
            } for f in failures[:25]
        ]

        return f"""
You are a senior QA engineer. Write an executive summary for a PM about this Playwright run.

Constraints:
- First paragraph: what broke and likely user/business impact.
- Then 3–7 bullets grouping failures by *root-cause pattern* using the provided signatures & counts.
- End with a *Risk* rating (Low/Medium/High) and a one-line justification.
- Keep it concise and actionable (<= 180 words).

Stats:
- total: {stats['total']} | passed: {stats['passed']} | failed: {stats['failed']} | skipped: {stats['skipped']} | flaky: {stats['flaky']}

Top failure patterns (signature -> count):
{json.dumps(patterns.get('top', []), ensure_ascii=False)}

CI:
- commit: {ci.get('commitHash')} ({ci.get('commitHref')})
- build: {ci.get('buildHref')}
- runner: Playwright {ci.get('runnerVersion')}

Sample failed tests (trimmed):
{json.dumps(failures_view, ensure_ascii=False, indent=2)}
""".strip()

    def _prompt_next_actions(
        self,
        stats: Dict[str, int],
        failures: List[Dict[str, Any]],
        patterns: Dict[str, Any],
        ci: Dict[str, Any],
    ) -> str:
        return f"""
You are a QA tech lead. Based on the patterns and error messages, list the top 5 **most impactful** next actions.
Format:
1. Imperative verb + outcome (why this unblocks risk)
2. Be specific (selectors/files/modules/timeouts)
3. If more info is needed, say exactly what evidence to capture (trace, screenshot, HAR).

Context:
- Stats: {stats}
- Patterns: {json.dumps(patterns.get('counts', {}), ensure_ascii=False)}
- CI build: {ci.get('buildHref')}
- Hints: If signature indicates ".alert-danger" not found, suggest asserting on a more stable selector or ensuring validation renders; if logout menu timeout, add explicit wait for profile icon/menu or mock auth state. Consider retry policy & per-test timeouts.

Return 5 bullets, each one line.
""".strip()


# ---------- small util ----------
def _compact(msg: str | None, max_len: int = 900) -> str:
    if not msg:
        return ""
    m = re.sub(r"\x1b\[[0-9;]*m", "", msg)  # strip ANSI
    m = re.sub(r"\s+\n", "\n", m)
    m = re.sub(r"\n{3,}", "\n\n", m)
    return (m[: max_len - 1] + "…") if len(m) > max_len else m
