"""Factory for initializing LLMs based on application configuration."""

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings


def get_llm(temperature: float = 0.0, max_tokens: int | None = None) -> BaseChatModel:
    """Instantiate and return the configured LLM."""
    settings = get_settings()

    if settings.llm_provider.lower() == "ollama":
        from langchain_ollama import ChatOllama
        
        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
            num_predict=max_tokens,
            format="json",  # Crucial for structured output from local models
        )
    else:
        # Default fallback to Gemini
        from langchain_google_genai import ChatGoogleGenerativeAI
        
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when llm_provider is 'gemini'")
            
        return ChatGoogleGenerativeAI(
            model="gemma-4-31b-it",
            api_key=settings.gemini_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
