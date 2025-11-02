# main.py
import argparse
from pathlib import Path

from analyzer import Analyzer
from integrations import SlackIntegration
from utils import AppConfig


def main():
    parser = argparse.ArgumentParser(description="Summarize Playwright JSON with OpenAI")
    parser.add_argument("-i", "--input", required=True, help="Path to Playwright JSON (e.g., reports/sample_results.json)")
    parser.add_argument("-t", "--title", default="Test Run Summary", help="Slack title")
    args = parser.parse_args()

    cfg = AppConfig()
    analyzer = Analyzer(cfg=cfg)
    result = analyzer.analyze_file(Path(args.input))

    print("\n=== Summary ===\n")
    print(result["summary"], "\n")
    print("=== Next actions ===\n")
    print(result["next_actions"], "\n")
    print("=== Stats ===")
    print(result["stats"], "\n")
    print("=== Top patterns ===")
    print(result.get("patterns", {}).get("top", []), "\n")

    slack = SlackIntegration(cfg)
    if slack.enabled():
        status = slack.post_summary(args.title, result)
        print(f"Posted to Slack (HTTP {status}).")


if __name__ == "__main__":
    main()
