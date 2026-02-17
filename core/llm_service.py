"""
LLM integration service with provider abstraction and fallback chain.

Supports multiple LLM providers (OpenAI, Anthropic) with automatic fallback.
"""
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, AsyncIterator
from enum import Enum

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

from bot.config import settings, LLMProvider


logger = logging.getLogger(__name__)


class LLMProviderBase(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> str:
        """Generate text response."""
        pass
    
    @abstractmethod
    async def generate_response_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> AsyncIterator[str]:
        """Generate streaming response."""
        pass


class OpenAIProvider(LLMProviderBase):
    """OpenAI provider implementation."""
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        """
        Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key
            model: Model name to use
        """
        from openai import AsyncOpenAI
        
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        logger.info(f"Initialized OpenAI provider with model {model}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception)
    )
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> str:
        """
        Generate text response from OpenAI.
        
        Args:
            messages: Conversation messages
            system_prompt: Optional system prompt
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated text response
        """
        try:
            full_messages = []
            
            if system_prompt:
                full_messages.append({"role": "system", "content": system_prompt})
            
            full_messages.extend(messages)
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"OpenAI generation error: {e}")
            raise
    
    async def generate_response_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> AsyncIterator[str]:
        """
        Generate streaming response from OpenAI.
        
        Args:
            messages: Conversation messages
            system_prompt: Optional system prompt
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            
        Yields:
            Text chunks as they are generated
        """
        try:
            full_messages = []
            
            if system_prompt:
                full_messages.append({"role": "system", "content": system_prompt})
            
            full_messages.extend(messages)
            
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True
            )
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"OpenAI streaming error: {e}")
            raise


class AnthropicProvider(LLMProviderBase):
    """Anthropic Claude provider implementation."""
    
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        """
        Initialize Anthropic provider.
        
        Args:
            api_key: Anthropic API key
            model: Model name to use
        """
        from anthropic import AsyncAnthropic
        
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        logger.info(f"Initialized Anthropic provider with model {model}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception)
    )
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> str:
        """
        Generate text response from Anthropic.
        
        Args:
            messages: Conversation messages
            system_prompt: Optional system prompt
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated text response
        """
        try:
            response = await self.client.messages.create(
                model=self.model,
                messages=messages,
                system=system_prompt or "",
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return response.content[0].text
            
        except Exception as e:
            logger.error(f"Anthropic generation error: {e}")
            raise
    
    async def generate_response_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> AsyncIterator[str]:
        """
        Generate streaming response from Anthropic.
        
        Args:
            messages: Conversation messages
            system_prompt: Optional system prompt
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            
        Yields:
            Text chunks as they are generated
        """
        try:
            async with self.client.messages.stream(
                model=self.model,
                messages=messages,
                system=system_prompt or "",
                temperature=temperature,
                max_tokens=max_tokens
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                    
        except Exception as e:
            logger.error(f"Anthropic streaming error: {e}")
            raise


class LLMService:
    """
    LLM service with provider abstraction and fallback chain.
    
    Automatically handles failures by falling back to alternative providers.
    """
    
    # System prompts
    REALTOR_BOT_SYSTEM_PROMPT = """Ты — ИИ-ассистент риелтора в Батуми. Кратко, по делу.

ЗАДАЧА: Выяснить 5 критериев: бюджет (валюту!), площадь, район, комнаты, стадию готовности.

ЖЁСТКИЕ ПРАВИЛА:
1. ОТВЕЧАЙ КОРОТКО — 1-2 предложения максимум
2. НЕ ПОВТОРЯЙ то что сказал клиент — сразу задавай следующий вопрос
3. НЕ СПРАШИВАЙ контакт до показа квартир
4. При неясной валюте — уточни: "Лари, доллары или рубли?"
5. Обращайся на "вы"

ПОРЯДОК:
- Собрал критерии → "Сейчас подберу варианты" → показал квартиры → клиент выбрал → спросил контакт

ПРИМЕР диалога:
Клиент: Хочу квартиру 50 м²
Плохо: Отлично, вы хотите 50 м² в Батуми. Это хороший размер. Теперь скажите пожалуйста бюджет...
Хорошо: Какой бюджет?
"""
    
    EXTRACTION_PROMPT = """Проанализируй диалог и извлеки информацию о клиенте в формате JSON.

Верни ТОЛЬКО JSON без пояснений:
{
    "budget": "строка с бюджетом или null",
    "size": "строка с площадью или null",
    "location": "строка с районом или null",
    "rooms": "строка с комнатами или null",
    "ready_status": "строка со стадией или null",
    "contact": "строка с контактом или null",
    "notes": "строка с пожеланиями или null",
    "is_complete": true/false  // все ли основные поля заполнены
}

ПРАВИЛА:
- budget: Извлеки ЧИСЛО с валютой ("100000$", "150000 USD", "400000 GEL"). Если клиент сказал "вменяемый" или "нормальный" без числа — верни null.
- size: Извлеки число в м² ("50 м²", "от 70 кв м")
- location: Название района (Старый Батуми, Новый бульвар, Гонио, Махинджаури)
- rooms: Количество комнат ("студия", "1", "2", "3+", "2-3 комнаты")
- ready_status: "готовое", "строящееся", "white frame", "black frame", "под чистовую"

ВАЖНО: Если значение неоднозначное или не содержит конкретики — верни null, не придумывай."""
    
    def __init__(
        self,
        primary_provider: LLMProvider,
        fallback_providers: List[LLMProvider],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 500,
        stream: bool = False
    ):
        """
        Initialize LLM service.
        
        Args:
            primary_provider: Primary LLM provider to use
            fallback_providers: List of fallback providers
            model: Model name to use
            temperature: Generation temperature
            max_tokens: Maximum tokens to generate
            stream: Enable streaming responses
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
        
        # Initialize providers
        self.providers: Dict[LLMProvider, LLMProviderBase] = {}
        
        # Setup primary provider
        self._setup_provider(primary_provider)
        
        # Setup fallback providers
        for provider in fallback_providers:
            self._setup_provider(provider)
        
        self.provider_order = [primary_provider] + fallback_providers
        logger.info(f"Initialized LLM service with provider order: {[p.value for p in self.provider_order]}")
    
    def _setup_provider(self, provider: LLMProvider) -> None:
        """Setup a provider instance."""
        if provider == LLMProvider.OPENAI:
            if settings.openai_api_key:
                self.providers[provider] = OpenAIProvider(
                    settings.openai_api_key,
                    self.model
                )
        elif provider == LLMProvider.ANTHROPIC:
            if settings.anthropic_api_key:
                anthropic_model = os.getenv(
                    "ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"
                )
                self.providers[provider] = AnthropicProvider(
                    settings.anthropic_api_key,
                    anthropic_model,
                )
    
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate response with fallback chain.
        
        Args:
            messages: Conversation messages
            system_prompt: Optional system prompt
            
        Returns:
            Generated response or None if all providers fail
        """
        if system_prompt is None:
            system_prompt = self.REALTOR_BOT_SYSTEM_PROMPT
        
        for provider_type in self.provider_order:
            provider = self.providers.get(provider_type)
            
            if not provider:
                logger.warning(f"Provider {provider_type.value} not configured, skipping")
                continue
            
            try:
                logger.info(f"Attempting generation with {provider_type.value}")
                
                response = await provider.generate_response(
                    messages=messages,
                    system_prompt=system_prompt,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens
                )
                
                logger.info(f"Successfully generated response with {provider_type.value}")
                return response
                
            except Exception as e:
                logger.error(
                    f"Failed to generate with {provider_type.value}: {e}, "
                    "trying next provider"
                )
                continue
        
        logger.error("All LLM providers failed")
        return None
    
    async def extract_client_info(
        self,
        conversation_history: List[Dict[str, str]]
    ) -> Dict:
        """
        Extract structured client information from conversation.
        
        Args:
            conversation_history: List of conversation messages
            
        Returns:
            Dictionary with extracted client information
        """
        extraction_message = {
            "role": "user",
            "content": f"Диалог:\n{json.dumps(conversation_history, ensure_ascii=False, indent=2)}"
        }
        
        response = await self.generate_response(
            messages=[extraction_message],
            system_prompt=self.EXTRACTION_PROMPT
        )
        
        if not response:
            return {"is_complete": False}
        
        try:
            # Extract JSON from response (in case there's extra text)
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
            
            return json.loads(response)
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse extraction response: {e}")
            return {"is_complete": False}
    
    async def transcribe_audio(self, audio_path: str) -> Optional[str]:
        """
        Transcribe audio file using Groq Whisper API (free tier).
        Falls back to OpenAI if Groq is not configured.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Transcribed text or None if failed
        """
        groq_key = os.getenv("GROQ_API_KEY")
        
        # Try Groq first (free)
        if groq_key:
            try:
                import httpx
                
                async with httpx.AsyncClient(timeout=60.0) as client:
                    with open(audio_path, "rb") as audio_file:
                        files = {"file": ("audio.oga", audio_file, "audio/ogg")}
                        data = {"model": "whisper-large-v3", "language": "ru"}
                        headers = {"Authorization": f"Bearer {groq_key}"}
                        
                        response = await client.post(
                            "https://api.groq.com/openai/v1/audio/transcriptions",
                            headers=headers,
                            files=files,
                            data=data
                        )
                        response.raise_for_status()
                        result = response.json()
                        
                        logger.info("Transcribed audio using Groq (free)")
                        return result.get("text")
                        
            except Exception as e:
                logger.warning(f"Groq transcription failed: {e}, falling back to OpenAI")
        
        # Fallback to OpenAI
        openai_provider = self.providers.get(LLMProvider.OPENAI)
        
        if not openai_provider:
            logger.error("No transcription provider available")
            return None
        
        try:
            with open(audio_path, "rb") as audio_file:
                transcript = await openai_provider.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file
                )
            
            return transcript.text
            
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None


__all__ = ["LLMService", "LLMProviderBase"]
