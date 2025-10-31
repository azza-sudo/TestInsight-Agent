import json
import requests
import os

# --- OpenAI SDK setup (pick ONE of the two sections below) ---

# If you're using the *new* OpenAI Python SDK (>=1.0):
# pip install "openai>=1.40"
from openai import OpenAI

from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing (set it as a GitHub Actions secret).")
client = OpenAI(api_key=OPENAI_API_KEY)

def load_test_results(file_path):
    with open(file_path, "r") as f:
        return json.load(f)

def generate_summary(results):
    prompt = f"""
    You are a QA Assistant. Summarize these test results in 3 bullet points:
    Total: {results['summary']['total']}, Passed: {results['summary']['passed']}, Failed: {results['summary']['failed']}
    Failures: {json.dumps(results['failures'], indent=2)}
    Highlight key failure trends and next step suggestions.
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return resp.choices[0].message.content

def send_to_slack(message):
    if not SLACK_WEBHOOK_URL:
        print("\n🔹 Slack not configured. Printing message locally:\n")
        print(message)
        return
    requests.post(SLACK_WEBHOOK_URL, json={"text": message})
    print("✅ Summary sent to Slack!")

if __name__ == "__main__":
    print("📊 Reading test results...")
    results = load_test_results("sample_results.json")
    print("🤖 Generating summary using AI...")
    summary = generate_summary(results)
    # send_to_slack(summary)
    print(summary)
