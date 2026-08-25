"""The providers Comodor can talk to, and what each one needs.

One table, because every part of the product asks the same questions about a
provider: what is it called, where does it live, what does it need from the
user, and which model should someone start with. The setup wizard, the config
loader, the model picker and `comodor doctor` all read from here, so adding a
provider is a single entry rather than a hunt.

Nearly all of these speak the OpenAI chat-completions dialect, which is why one
adapter covers them. Anthropic is the exception and has its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: How Comodor identifies itself to a provider that asks. OpenRouter shows both
#: on its model pages and its leaderboards, and takes the icon beside the name
#: from the favicon of the referer - so this is the site, not the repository.
SITE = "https://comodor.ai"
APP_NAME = "Comodor"


@dataclass(frozen=True)
class ProviderSpec:
    """Everything known about a provider before the user configures it."""

    id: str
    label: str
    kind: str = "openai"              # wire protocol: openai | anthropic
    base_url: str = ""
    #: Where to get a key. Shown in the wizard, so it must be the real page.
    keys_url: str = ""
    #: A short line explaining who this is for, shown next to the choice.
    blurb: str = ""
    #: Sensible starting model. The user can change it later.
    default_model: str = ""
    #: A few well-known models, offered when the API cannot be listed.
    models: tuple[str, ...] = ()
    #: Environment variable honoured as an override, for CI.
    env_key: str = ""
    #: Local runtimes need no key.
    needs_key: bool = True
    #: Ranking in the setup wizard; lower comes first.
    rank: int = 50
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def local(self) -> bool:
        return not self.needs_key


CATALOGUE: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        keys_url="https://openrouter.ai/keys",
        blurb="One key, hundreds of models from every lab. The easiest start.",
        default_model="anthropic/claude-sonnet-4.5",
        models=("anthropic/claude-sonnet-4.5", "anthropic/claude-opus-4.1",
                "openai/gpt-4o", "google/gemini-2.5-pro",
                "deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct"),
        env_key="OPENROUTER_API_KEY",
        rank=1,
        # OpenRouter attributes a request to an application by these two
        # headers and shows it on its model pages and leaderboards. The icon
        # beside the name is the favicon of the referer, which is why that is
        # the site rather than the repository.
        headers={"HTTP-Referer": SITE, "X-Title": APP_NAME},
    ),
    ProviderSpec(
        id="anthropic",
        label="Anthropic",
        kind="anthropic",
        base_url="https://api.anthropic.com/v1",
        keys_url="https://console.anthropic.com/settings/keys",
        blurb="Claude, direct from the source. Strongest at long agentic work.",
        # These have to be models the pricing registry knows. It did not know
        # any of the three that were here, so the wizard's own default landed
        # on an unpriced model: the context gauge read a fallback 128k instead
        # of a million, and the spend limit could not be enforced at all.
        default_model="claude-sonnet-5",
        models=("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"),
        env_key="ANTHROPIC_API_KEY",
        rank=2,
    ),
    ProviderSpec(
        id="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        keys_url="https://platform.openai.com/api-keys",
        blurb="GPT models, direct.",
        default_model="gpt-4o",
        models=("gpt-4o", "gpt-4o-mini", "gpt-4.1", "o3-mini"),
        env_key="OPENAI_API_KEY",
        rank=3,
    ),
    ProviderSpec(
        id="google",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        keys_url="https://aistudio.google.com/apikey",
        blurb="Gemini, through Google's OpenAI-compatible endpoint. Generous free tier.",
        default_model="gemini-2.5-flash",
        models=("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"),
        env_key="GOOGLE_API_KEY",
        rank=4,
    ),
    ProviderSpec(
        id="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        keys_url="https://platform.deepseek.com/api_keys",
        blurb="Very cheap, strong at code.",
        default_model="deepseek-chat",
        models=("deepseek-chat", "deepseek-reasoner"),
        env_key="DEEPSEEK_API_KEY",
        rank=5,
    ),
    ProviderSpec(
        id="xai",
        label="xAI (Grok)",
        base_url="https://api.x.ai/v1",
        keys_url="https://console.x.ai",
        blurb="Grok models.",
        default_model="grok-4",
        models=("grok-4", "grok-3", "grok-3-mini"),
        env_key="XAI_API_KEY",
        rank=6,
    ),
    ProviderSpec(
        id="mistral",
        label="Mistral",
        base_url="https://api.mistral.ai/v1",
        keys_url="https://console.mistral.ai/api-keys",
        blurb="European, open-weight friendly.",
        default_model="mistral-large-latest",
        models=("mistral-large-latest", "mistral-small-latest", "codestral-latest"),
        env_key="MISTRAL_API_KEY",
        rank=7,
    ),
    ProviderSpec(
        id="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        keys_url="https://console.groq.com/keys",
        blurb="Open models at very high speed.",
        default_model="llama-3.3-70b-versatile",
        models=("llama-3.3-70b-versatile", "qwen-2.5-coder-32b",
                "deepseek-r1-distill-llama-70b"),
        env_key="GROQ_API_KEY",
        rank=8,
    ),
    ProviderSpec(
        id="cerebras",
        label="Cerebras",
        base_url="https://api.cerebras.ai/v1",
        keys_url="https://cloud.cerebras.ai",
        blurb="The fastest inference available for open models.",
        default_model="llama-3.3-70b",
        models=("llama-3.3-70b", "qwen-3-32b"),
        env_key="CEREBRAS_API_KEY",
        rank=9,
    ),
    ProviderSpec(
        id="moonshot",
        label="Moonshot (Kimi)",
        base_url="https://api.moonshot.ai/v1",
        keys_url="https://platform.moonshot.ai/console/api-keys",
        blurb="Kimi models, strong at long context and agentic tasks.",
        default_model="kimi-k2-0905-preview",
        models=("kimi-k2-0905-preview", "moonshot-v1-128k"),
        env_key="MOONSHOT_API_KEY",
        rank=10,
    ),
    ProviderSpec(
        id="zai",
        label="Z.AI (GLM)",
        base_url="https://api.z.ai/api/paas/v4",
        keys_url="https://z.ai/manage-apikey/apikey-list",
        blurb="GLM models — a popular low-cost coding plan.",
        default_model="glm-4.6",
        models=("glm-4.6", "glm-4.5", "glm-4.5-air"),
        env_key="ZAI_API_KEY",
        rank=11,
    ),
    ProviderSpec(
        id="qwen",
        label="Qwen (DashScope)",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        keys_url="https://bailian.console.alibabacloud.com",
        blurb="Alibaba's Qwen models, including the coder line.",
        default_model="qwen-max",
        models=("qwen-max", "qwen-plus", "qwen3-coder-plus"),
        env_key="DASHSCOPE_API_KEY",
        rank=12,
    ),
    ProviderSpec(
        id="together",
        label="Together AI",
        base_url="https://api.together.xyz/v1",
        keys_url="https://api.together.ai/settings/api-keys",
        blurb="A broad catalogue of open models.",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        models=("meta-llama/Llama-3.3-70B-Instruct-Turbo",
                "Qwen/Qwen2.5-Coder-32B-Instruct"),
        env_key="TOGETHER_API_KEY",
        rank=13,
    ),
    ProviderSpec(
        id="fireworks",
        label="Fireworks",
        base_url="https://api.fireworks.ai/inference/v1",
        keys_url="https://fireworks.ai/account/api-keys",
        blurb="Fast hosting for open models.",
        default_model="accounts/fireworks/models/llama-v3p3-70b-instruct",
        models=("accounts/fireworks/models/llama-v3p3-70b-instruct",
                "accounts/fireworks/models/deepseek-v3"),
        env_key="FIREWORKS_API_KEY",
        rank=14,
    ),
    ProviderSpec(
        id="xiaomi",
        label="Xiaomi MiMo",
        base_url="https://token-plan-sgp.xiaomimimo.com/v1",
        keys_url="https://xiaomimimo.com",
        blurb="MiMo models.",
        default_model="mimo-v2.5-pro",
        models=("mimo-v2.5-pro",),
        env_key="XIAOMI_API_KEY",
        rank=15,
    ),
    ProviderSpec(
        id="ollama",
        label="Ollama (local)",
        base_url="http://localhost:11434/v1",
        keys_url="https://ollama.com/download",
        blurb="Runs on your machine. No key, no cost, no network.",
        default_model="qwen2.5-coder:14b",
        models=("qwen2.5-coder:14b", "llama3.3", "deepseek-r1:14b"),
        env_key="OLLAMA_API_KEY",
        needs_key=False,
        rank=20,
    ),
    ProviderSpec(
        id="lmstudio",
        label="LM Studio (local)",
        base_url="http://localhost:1234/v1",
        keys_url="https://lmstudio.ai",
        blurb="Runs on your machine, with a desktop UI for managing models.",
        default_model="local-model",
        models=("local-model",),
        env_key="LMSTUDIO_API_KEY",
        needs_key=False,
        rank=21,
    ),
    ProviderSpec(
        id="local",
        label="Local LLM",
        # Empty because there is nothing to point at until a model is running,
        # and the port it lands on is chosen at startup. `LocalProvider` fills
        # this in once it has a server. A URL written here would be a number
        # that is wrong the next time.
        base_url="",
        keys_url="",
        blurb="Downloaded to this machine and run here. No key, no account, "
              "and it keeps working with the network unplugged.",
        default_model="",
        env_key="",
        needs_key=False,
        rank=19,
        kind="local",
    ),
    ProviderSpec(
        id="custom",
        label="Something else",
        base_url="",
        keys_url="",
        blurb="Any other OpenAI-compatible endpoint — you supply the URL.",
        default_model="",
        env_key="CUSTOM_API_KEY",
        rank=99,
    ),
)

BY_ID: dict[str, ProviderSpec] = {spec.id: spec for spec in CATALOGUE}


def get(provider_id: str) -> ProviderSpec | None:
    return BY_ID.get(provider_id)


def offered() -> list[ProviderSpec]:
    """The catalogue in the order the setup wizard should present it."""
    return sorted(CATALOGUE, key=lambda spec: (spec.rank, spec.label))


def hosted() -> list[ProviderSpec]:
    return [spec for spec in offered() if spec.needs_key and spec.id != "custom"]


def local() -> list[ProviderSpec]:
    return [spec for spec in offered() if not spec.needs_key]
