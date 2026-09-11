"""12 · llm — connect to the model.

Every model call in the app goes through one place: get_llm(). It returns a
LangChain chat model backed by a LiteLLM *Router* (the litellm SDK, running
in-process — NOT a separate proxy service):

    primary   -> Vertex AI Gemini  (config.LLM_MODEL_NAME, served from
                                    config.LLM_LOCATION)
    fallback  -> Groq              (config.FALLBACK_MODEL_NAME), used only if
                                    the Vertex call errors after num_retries

The Gemini deployment is pinned to LLM_LOCATION, not the project-wide
LOCATION: no Gemini model is served from every region, and Gemini 3.x is
served only from the "global" endpoint, so the model id and the location it
is asked for are one decision. Both live in config.py.

The app always asks for one logical model ("hr-llm"); the Router decides
what actually serves it. Adding, swapping, or reordering backends is a
change here and in config.py — never in the calling code (agent.py,
guardrails.py).

Why the SDK and not a hosted proxy: with one app there's nothing a separate
gateway service buys that this doesn't — provider-agnostic calls and
automatic failover both live in the Router. It also removes an entire class
of deployment problem (a second Cloud Run service, its IAM binding, and
minting a Google ID token per request). Vertex auth is plain Application
Default Credentials, exactly as a direct Gemini call would use.
"""

import logging

import litellm
from langchain_litellm import ChatLiteLLMRouter
from litellm import Router

from hr_assistant import config

logger = logging.getLogger(__name__)

# Gemini accepts params (e.g. some tool/response-format options) that Groq's
# OpenAI-compatible endpoint rejects. Drop unsupported params on the way to
# whichever backend serves the call, rather than 400-ing on the fallback.
litellm.drop_params = True

_PRIMARY_GROUP = "hr-llm"
_FALLBACK_GROUP = "hr-llm-fallback"

# One Router for the whole process — it holds per-deployment state
# (cooldowns, retry counters). get_llm() is called per guardrail check and
# once per agent build, so a fresh Router each call would throw that away.
_router: "Router | None" = None


def _warn_if_region_cannot_serve_model() -> None:
    """Say so up front when the model/location pair can't work.

    A model that isn't served from the requested location comes back as a 404
    "model not found" on the first real question, and the Router then quietly
    fails over to Groq — so the app looks fine while never once using Gemini.
    Gemini 3.x is the case that bites today (global endpoint only); this is a
    warning, not an error, so a future regional rollout needs no code change.
    """
    if config.LLM_MODEL_NAME.startswith("gemini-3") and config.LLM_LOCATION != "global":
        logger.warning(
            "LLM_MODEL_NAME=%s is served only from the Vertex global endpoint, "
            "but LLM_LOCATION=%s. Expect 404s and a silent fallback to %s. "
            "Set LLM_LOCATION=global.",
            config.LLM_MODEL_NAME, config.LLM_LOCATION, config.FALLBACK_MODEL_NAME,
        )


def _get_router() -> Router:
    global _router
    if _router is None:
        _warn_if_region_cannot_serve_model()
        _router = Router(
            model_list=[
                {
                    "model_name": _PRIMARY_GROUP,
                    "litellm_params": {
                        "model": f"vertex_ai/{config.LLM_MODEL_NAME}",
                        "vertex_project": config.PROJECT_ID,
                        # NOT config.LOCATION — see the module docstring.
                        "vertex_location": config.LLM_LOCATION,
                    },
                },
                {
                    "model_name": _FALLBACK_GROUP,
                    "litellm_params": {
                        "model": f"groq/{config.FALLBACK_MODEL_NAME}",
                        "api_key": config.GROQ_API_KEY,
                    },
                },
            ],
            # Retry the primary a couple of times, THEN cross over to Groq.
            num_retries=2,
            fallbacks=[{_PRIMARY_GROUP: [_FALLBACK_GROUP]}],
        )
    return _router


def get_llm():
    """The app's chat model: Gemini primary, Groq fallback, one retry policy.

    A LangChain chat model (supports tool calling and structured output), so
    agent.py and guardrails.py use it unchanged. temperature=0 is set once
    here — the single source of truth for both backends."""
    return ChatLiteLLMRouter(router=_get_router(),
                model_name=_PRIMARY_GROUP, 
            temperature=0)
