import json
import requests
import openai
from config import OPENAI_API_KEY, SLACK_WEBHOOK_URL

openai.api_key = OPENAI_API_KEY

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
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response["choices"][0]["message"]["content"]

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
    send_to_slack(summary)
