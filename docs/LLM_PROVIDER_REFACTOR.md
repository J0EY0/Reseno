# LLM Provider Refactor

## Goal

Reseno should keep provider differences inside the backend provider layer. The
agent runtime should select a saved model config and call one unified LLM
interface without knowing whether the underlying provider is OpenAI, Anthropic,
Gemini, or an OpenAI-compatible endpoint.

## Provider Modes

Reseno supports three configuration modes:

- Cloud provider: a curated brand with backend model discovery.
- Local runtime: an OpenAI-compatible endpoint with optional backend model
  discovery.
- Custom cloud API: manual endpoint configuration with an explicit API family.

Cloud providers must support model discovery. If a provider cannot return a
model list, it should not be available as a cloud provider; users can configure
it through custom cloud API instead.

Initial cloud providers:

- OpenAI
- Anthropic
- Google Gemini
- DeepSeek
- Qwen
- MiniMax
- Z.ai
- Moonshot AI
- xAI

Providers intentionally excluded from the cloud list include OpenRouter,
Mistral AI, SiliconCloud, ModelScope, Azure OpenAI, Bedrock, Cloudflare,
and Perplexity.

Initial local providers:

- Ollama
- vLLM
- SGLang

## API Families

Saved model configs store both `provider` and `apiFamily`.

- `provider` is the brand/display identity.
- `apiFamily` selects the backend adapter.

Supported API families:

- `openai_responses`
- `openai_compatible_chat`
- `anthropic_messages`
- `google_gemini`

Cloud provider `apiFamily` values come from the backend provider manifest and
are not user-editable. Custom cloud API users must explicitly choose an API
family. Local model configs use OpenAI-compatible chat.

## Model Discovery

Cloud provider configuration requires a successful manual model discovery step.
The user fills credentials, clicks "fetch models", chooses a model from the
returned list, and then saves.

Local provider discovery uses the configured local OpenAI-compatible API URL.
Users can still type a local model name manually when discovery is unavailable.

Discovery results are not stored. The database stores only the selected model
and the selected model's metadata snapshot.

Discovery failure is shown as a generic user-facing message:

- "获取模型失败，请重试"

An empty model list is shown as:

- "未获取到可用模型，请重试"

Provider error bodies, headers, tracebacks, and secrets are not shown in the UI.

## Model Metadata

The model dropdown is sourced only from provider discovery. LiteLLM metadata is
not used to recommend or list models.

LiteLLM metadata is only a fallback for runtime metadata:

1. Provider discovery metadata
2. LiteLLM context/max-output metadata
3. Conservative fallback context window: `32768`
4. Manual override for custom/local configs

Saved configs always have a positive `contextWindowTokens` value.

## Parameters And Capabilities

Cloud providers hide and store `temperature`, `topP`, and `maxTokens` as null.
Null request parameters are omitted so providers use their defaults.

Local and custom configs may expose advanced request parameters.

System prompts are not user-configurable. The backend owns the system prompt and
maps it through each provider adapter.

Saved capability fields:

- `supportsImage`
- `supportsThinking`
- `thinkingEnabled`

Cloud provider capabilities are inferred from provider metadata and conservative
rules. Users cannot override them. Unknown image/thinking capability is treated
as unsupported.

Custom cloud API users may declare `supportsImage` and `supportsThinking`.
Local model configs default both capabilities to false and do not expose manual
capability editing.

Thinking is a boolean advanced option. It defaults on when the selected model
supports thinking, but reasoning/thinking text is never streamed or displayed to
the user.

Image input is gated in both frontend and backend. If a request contains an
image but the selected model does not support images, the backend rejects the
request before calling the provider.

PDF/DOCX and similar documents are locally parsed into text and do not require
model image support.
