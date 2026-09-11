"""
Swappable generation backends.

Embeddings stay Gemini-specific (Anthropic's API doesn't serve an embedding
endpoint, so `get_embedding` in rag_eval.py always calls Gemini regardless
of which provider you pick here). What's swappable is the *text generation*
step -- answering the question, and the two judge calls -- which is the
part that actually burns quota/money per eval run, and the part you don't
want locked to a single paid provider.

Usage:
    provider = get_provider("claude")   # or "gemini"
    text = provider.generate(prompt)

Both providers implement the same one-method interface, so nothing else in
rag_eval.py or run_eval.py needs to know or care which one is active.
"""

import os


class GeminiProvider:
    def __init__(self, api_key=None, model=None):
        from google import genai

        self._client = genai.Client(api_key=api_key or os.environ["GOOGLE_API_KEY"])
        self._model = model or os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

    def generate(self, prompt):
        response = self._client.models.generate_content(model=self._model, contents=prompt)
        return response.text

    @property
    def embed_client(self):
        """Exposes the underlying genai client for embeddings (see note above)."""
        return self._client


class ClaudeProvider:
    def __init__(self, api_key=None, model=None):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        # Check https://docs.claude.com/en/docs/about-claude/models for current model IDs
        # if this default ever 404s -- override with ANTHROPIC_MODEL in .env instead of
        # editing this file.
        self._model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

    def generate(self, prompt):
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text


def get_provider(name=None, **kwargs):
    """
    name: "claude" or "gemini". Falls back to the LLM_PROVIDER env var, then
    to "claude" (since the whole point of this file is to not force you
    onto the paid-Gemini path by default).
    """
    name = (name or os.environ.get("LLM_PROVIDER", "claude")).lower()
    if name == "claude":
        return ClaudeProvider(**kwargs)
    if name == "gemini":
        return GeminiProvider(**kwargs)
    raise ValueError(f"Unknown provider '{name}' -- expected 'claude' or 'gemini'.")
