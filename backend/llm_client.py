"""
Groq LLM Client
----------------
Thin wrapper around the Groq API (OpenAI-compatible /chat/completions
endpoint) used by the Planning, Budget, and Research agents.

Set your key as an environment variable before running the backend:

    export GROQ_API_KEY="gsk_xxxxxxxxxxxxxxxxxxxx"     (Mac/Linux)
    setx GROQ_API_KEY "gsk_xxxxxxxxxxxxxxxxxxxx"        (Windows)

Get a free key at: https://console.groq.com/keys

If no key is set (or a call fails/times out), every agent that uses this
client automatically falls back to its rule-based logic, so the project
still runs end-to-end without an API key.
"""

import json
import os

from dotenv import load_dotenv
load_dotenv()

import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def is_configured() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def call_llm(system_prompt: str, user_prompt: str, json_mode: bool = False,
             temperature: float = 0.4, timeout: int = 20) -> str:
    """
    Calls the Groq chat completions endpoint and returns the raw text of
    the model's reply. Raises on any failure — callers are expected to
    catch exceptions and fall back to rule-based logic.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set in the environment.")

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    resp = requests.post(
        GROQ_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def call_llm_json(system_prompt: str, user_prompt: str, **kwargs) -> dict:
    """Calls the LLM expecting a JSON object back, and parses it."""
    raw = call_llm(system_prompt, user_prompt, json_mode=True, **kwargs)
    # Strip accidental markdown code fences, just in case.
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned)
