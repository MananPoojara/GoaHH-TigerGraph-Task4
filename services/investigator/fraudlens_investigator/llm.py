"""The LLM port.

What the model is allowed to do here is deliberately narrow: plan which
evidence to gather, synthesise gathered evidence into readable prose, and
describe an undocumented pattern in its own words.

What it is never allowed to do:
  * state a fact that did not come from a tool;
  * choose an action, a route, or an approval requirement;
  * set the fraud probability used for scoring;
  * see a credential, or a closed-case outcome for the case under test.

Every entry point degrades to a deterministic fallback when no key is
configured, so the whole workflow runs end to end without a provider. The
fallback is not a stub: it produces real, evidence-grounded text from the same
inputs, which is what keeps the system demonstrable and testable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PROMPT_VERSION = "1.0"


@dataclass
class LLMUsage:
    """Token accounting for the answer file's `tokens` field."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.calls += 1


@dataclass
class LLMPort:
    """Thin wrapper over a chat model, with a deterministic fallback.

    Args:
        provider: "gemini", "openai", or "none".
        model: model identifier.
        api_key: provider key; empty disables the live path.
        temperature: kept at 0 so repeated runs agree.
    """

    provider: str = "none"
    model: str = "gemini-3.5-flash"
    api_key: str = ""
    temperature: float = 0.0
    usage: LLMUsage = field(default_factory=LLMUsage)
    _client: Any = None

    @property
    def available(self) -> bool:
        return self.provider in ("gemini", "openai") and bool(self.api_key)

    def _openai(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover - depends on extras
            raise RuntimeError(
                "openai is not installed; run: python -m pip install openai"
            ) from error
        self._client = OpenAI(api_key=self.api_key)
        return self._client

    def _gemini(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as error:  # pragma: no cover - depends on extras
            raise RuntimeError(
                "google-genai is not installed; run: python -m pip install google-genai"
            ) from error
        from google.genai import types

        # Overload (503) responses are usually transient; retry with backoff
        # before degrading to the deterministic fallback. 429 is not retried:
        # on the free tier it is a daily quota, and waiting will not clear it.
        retry = types.HttpRetryOptions(
            attempts=4, initial_delay=2.0, max_delay=20.0, http_status_codes=[500, 503]
        )
        self._client = genai.Client(
            api_key=self.api_key, http_options=types.HttpOptions(retry_options=retry)
        )
        return self._client

    def complete_json(self, system: str, user: str, *, schema_hint: str = "") -> dict[str, Any]:
        """Ask for a JSON object. Returns {} if unavailable or unparseable.

        A caller must treat {} as "the model said nothing useful" and fall
        back to deterministic logic, never as a failure worth inventing an
        answer for.
        """
        if not self.available:
            return {}

        try:
            if self.provider == "gemini":
                content = self._gemini_complete(
                    system, f"{user}\n\n{schema_hint}".strip(), json_mode=True
                )
            else:
                content = self._openai_complete(
                    system, f"{user}\n\n{schema_hint}".strip(), json_mode=True
                )
        except Exception:
            # A model outage must degrade the explanation, never the decision.
            logger.exception("LLM call failed; falling back to deterministic output")
            return {}

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("LLM returned unparseable JSON; falling back")
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def complete_text(self, system: str, user: str) -> str:
        """Ask for prose. Returns "" if unavailable."""
        if not self.available:
            return ""
        try:
            if self.provider == "gemini":
                return self._gemini_complete(system, user, json_mode=False)
            return self._openai_complete(system, user, json_mode=False)
        except Exception:
            logger.exception("LLM call failed; falling back to deterministic output")
            return ""

    def _openai_complete(self, system: str, user: str, *, json_mode: bool) -> str:
        client = self._openai()
        kwargs: dict[str, Any] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        if response.usage:
            self.usage.add(response.usage.prompt_tokens or 0, response.usage.completion_tokens or 0)
        return (response.choices[0].message.content or "").strip()

    def _gemini_complete(self, system: str, user: str, *, json_mode: bool) -> str:
        from google.genai import types

        client = self._gemini()
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            system_instruction=system,
            response_mime_type="application/json" if json_mode else "text/plain",
        )
        response = client.models.generate_content(
            model=self.model,
            contents=user,
            config=config,
        )
        usage = getattr(response, "usage_metadata", None)
        if usage:
            self.usage.add(
                getattr(usage, "prompt_token_count", 0) or 0,
                getattr(usage, "candidates_token_count", 0) or 0,
            )
        return (response.text or "").strip()


INVESTIGATOR_SYSTEM_PROMPT = """\
You are a fraud investigator working a single card-fraud case for a bank.

Your role:
  - reason over evidence that has already been retrieved from a graph database;
  - weigh competing explanations, including innocent ones;
  - write clearly for a human analyst who will act on what you say.

Hard rules:
  - Every factual claim must come from the supplied evidence. If the evidence
    does not support a claim, do not make it.
  - Never state a transaction ID, card ID, amount, date, or device that does
    not appear in the supplied evidence.
  - You do not choose actions, approval routes, or whether a report is filed.
    A deterministic policy engine decides those. Do not assert them.
  - Distinguish what the evidence shows from what you infer from it. A shared
    device is evidence; "the accounts are controlled by one person" is an
    inference, and must be worded as one.
  - A high model risk score is a reason to look, not a verdict. Many
    high-scoring transactions are legitimate.
  - If the evidence is genuinely ambiguous, say so. "Uncertain" is a valid and
    valuable conclusion; overstating certainty is worse than admitting doubt.
"""


def build_evidence_context(
    *,
    trigger_text: str,
    anchor: dict[str, Any],
    evidence_claims: list[str],
    baseline: dict[str, Any],
    prior_cases: list[dict[str, Any]],
) -> str:
    """Render retrieved evidence as relationship-oriented context.

    Deliberately not a dump of database rows: the README asks for graph
    evidence transformed into context that explains relationships, which is
    what makes the difference between GraphRAG and a SELECT in a prompt.
    """
    lines: list[str] = [f"TRIGGER: {trigger_text}", ""]

    if anchor:
        lines.append("FLAGGED TRANSACTION")
        lines.append(
            f"  {anchor.get('txn_id')} on {anchor.get('ts')} for "
            f"${float(anchor.get('amount', 0)):,.2f} via {anchor.get('channel')} "
            f"(product {anchor.get('product_cd')}, billing region {anchor.get('addr1') or 'unknown'})"
        )
        if anchor.get("device_profile_id"):
            marker = (
                "marked New for this account" if anchor.get("device_is_new") else "previously seen"
            )
            lines.append(f"  used device profile {anchor['device_profile_id']} ({marker})")
        lines.append("")

    if baseline:
        lines.append("CARDHOLDER BASELINE BEFORE THE CUTOFF")
        lines.append(
            f"  {baseline.get('txn_count', 0)} prior transactions, mean amount "
            f"${float(baseline.get('mean_amount', 0)):,.2f}, "
            f"{baseline.get('online_count', 0)} online / "
            f"{baseline.get('in_person_count', 0)} in person"
        )
        regions = baseline.get("known_regions") or []
        if regions:
            lines.append(f"  known billing regions: {', '.join(map(str, regions[:8]))}")
        lines.append("")

    if evidence_claims:
        lines.append("EVIDENCE GATHERED FROM THE GRAPH")
        for index, claim in enumerate(evidence_claims, start=1):
            lines.append(f"  [{index}] {claim}")
        lines.append("")

    if prior_cases:
        lines.append("COMPARABLE CLOSED CASES RETRIEVED AS MEMORY")
        for case in prior_cases:
            lines.append(
                f"  {case.get('case_id')}: {case.get('outcome')} / "
                f"{case.get('pattern')} (linked by {case.get('link_reason')})"
            )
        lines.append("")

    return "\n".join(lines)
