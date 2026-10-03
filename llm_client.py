import json
import logging

from groq import Groq

logger = logging.getLogger(__name__)

# Approximate token budget for a single prompt.
# Groq free tier: 12,000 TPM for llama-3.3-70b-versatile.
# Reserve 1,024 for the completion; leave the rest for the prompt.
PROMPT_TOKEN_BUDGET = 9_000

# Response tokens — keep small; our JSON responses are short.
MAX_COMPLETION_TOKENS = 1_024


def estimate_tokens(text: str) -> int:
    """
    Fast approximation: 1 token ≈ 4 characters (works well for English + JSON).
    Used only for pre-flight budget checks, not for billing.
    """
    return max(1, len(text) // 4)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that some models add around JSON."""
    t = text.strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


class LLMClient:
    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
    ):
        if not api_key:
            raise ValueError("Groq API key is required")
        self.client = Groq(api_key=api_key)
        self.model = model

    def generate(self, prompt: str, temperature: float = 0.2) -> str:
        estimated = estimate_tokens(prompt)
        if estimated > PROMPT_TOKEN_BUDGET:
            logger.warning(
                "Prompt is ~%d tokens — above budget of %d. "
                "Consider reducing field counts or catalog size.",
                estimated,
                PROMPT_TOKEN_BUDGET,
            )

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=MAX_COMPLETION_TOKENS,
        )

        logger.debug(
            "LLM usage — prompt: %d  completion: %d  total: %d",
            completion.usage.prompt_tokens,
            completion.usage.completion_tokens,
            completion.usage.total_tokens,
        )

        return completion.choices[0].message.content

    def generate_json(self, prompt: str, temperature: float = 0.2) -> dict:
        raw = self.generate(prompt, temperature)
        cleaned = _strip_fences(raw)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.debug("First parse failed — asking model to repair JSON.")
            repair_prompt = f"Return ONLY valid JSON. Fix:\n\n{cleaned}"
            repaired = _strip_fences(self.generate(repair_prompt, temperature=0))
            return json.loads(repaired)