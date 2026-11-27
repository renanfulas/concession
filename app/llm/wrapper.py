from app.core.config import get_settings
from app.core.errors import ProviderError
from app.llm.base import BaseLLMProvider

MISSING_CREDENTIALS = "missing_credentials"
PROVIDER_TIMEOUT = "provider_timeout"
PROVIDER_REQUEST_ERROR = "provider_request_error"
EMPTY_RESPONSE = "empty_response"

# Sampling temperature used for every provider client. Read by the opt-in
# real-LLM eval report, so keep it as the single source.
DEFAULT_TEMPERATURE = 0.0


class LLMWrapper(BaseLLMProvider):
    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.temperature = DEFAULT_TEMPERATURE
        # Model id and token usage of the last successful call, when the
        # provider returns them. Never holds prompt or answer text.
        self.last_call_metadata: dict[str, object] | None = None
        settings = get_settings()

        if provider == "openai":
            openai_api_key = api_key or settings.openai_api_key
            if not openai_api_key:
                raise ProviderError(
                    "provider credentials are not configured",
                    failure_kind=MISSING_CREDENTIALS,
                )
            from langchain_openai import ChatOpenAI

            self.client = ChatOpenAI(
                api_key=openai_api_key,
                model=model,
                temperature=self.temperature,
            )
        elif provider == "anthropic":
            anthropic_api_key = api_key or settings.anthropic_api_key
            if not anthropic_api_key:
                raise ProviderError(
                    "provider credentials are not configured",
                    failure_kind=MISSING_CREDENTIALS,
                )
            from langchain_anthropic import ChatAnthropic

            self.client = ChatAnthropic(
                api_key=anthropic_api_key,
                model=model,
                temperature=self.temperature,
            )
        else:
            raise ValueError(f"Provider {provider} is not supported")

    def generate_answer(self, prompt: str) -> str:
        try:
            response = self.client.invoke(prompt)
            content = str(response.content)
            self.last_call_metadata = _response_metadata(response)
        except Exception as exc:
            raise ProviderError(
                "provider request failed",
                failure_kind=_classify_provider_exception(exc),
            ) from exc

        if not content.strip():
            raise ProviderError(
                "provider returned empty response",
                failure_kind=EMPTY_RESPONSE,
            )

        return content

    async def complete(self, prompt: str) -> str:
        try:
            response = await self.client.ainvoke(prompt)
            content = str(response.content)
            self.last_call_metadata = _response_metadata(response)
        except Exception as exc:
            raise ProviderError(
                "provider request failed",
                failure_kind=_classify_provider_exception(exc),
            ) from exc

        if not content.strip():
            raise ProviderError(
                "provider returned empty response",
                failure_kind=EMPTY_RESPONSE,
            )

        return content


def _response_metadata(response: object) -> dict[str, object]:
    """Extract model id and token counts from a LangChain message, if exposed."""
    metadata: dict[str, object] = {}
    response_metadata = getattr(response, "response_metadata", None)
    if isinstance(response_metadata, dict):
        model_id = response_metadata.get("model_name") or response_metadata.get("model")
        if isinstance(model_id, str) and model_id:
            metadata["model"] = model_id
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        counts = {
            key: usage[key]
            for key in ("input_tokens", "output_tokens", "total_tokens")
            if isinstance(usage.get(key), int)
        }
        if counts:
            metadata["usage"] = counts
    return metadata


def _classify_provider_exception(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return PROVIDER_TIMEOUT

    exception_labels = (
        exc.__class__.__name__,
        exc.__class__.__module__,
    )
    normalized_labels = " ".join(exception_labels).lower()
    if "timeout" in normalized_labels or "timedout" in normalized_labels:
        return PROVIDER_TIMEOUT

    return PROVIDER_REQUEST_ERROR
