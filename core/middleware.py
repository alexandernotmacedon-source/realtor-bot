"""
Middleware для обработки сообщений и error handling.

Предоставляет:
- Логирование всех сообщений
- Rate limiting
- Error handling
- Метрики
"""
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from typing import Callable, Dict, Optional

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import settings


logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter для защиты от спама.
    
    Использует sliding window алгоритм для отслеживания запросов.
    """
    
    def __init__(
        self,
        max_requests: int = 10,
        window_seconds: int = 60
    ):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Window duration in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[int, list[float]] = defaultdict(list)
        logger.info(
            f"Initialized rate limiter: {max_requests} requests per {window_seconds}s"
        )
    
    def is_allowed(self, user_id: int) -> bool:
        """
        Check if user is allowed to make request.
        
        Args:
            user_id: User ID to check
            
        Returns:
            True if allowed, False if rate limited
        """
        if not settings.rate_limit_enabled:
            return True
        
        now = time.time()
        cutoff = now - self.window_seconds
        
        # Remove old requests outside window
        self._requests[user_id] = [
            req_time for req_time in self._requests[user_id]
            if req_time > cutoff
        ]
        
        # Check if limit exceeded
        if len(self._requests[user_id]) >= self.max_requests:
            logger.warning(f"Rate limit exceeded for user {user_id}")
            return False
        
        # Add current request
        self._requests[user_id].append(now)
        return True
    
    def get_remaining_requests(self, user_id: int) -> int:
        """Get remaining requests for user."""
        now = time.time()
        cutoff = now - self.window_seconds
        
        # Count requests in current window
        recent_requests = sum(
            1 for req_time in self._requests[user_id]
            if req_time > cutoff
        )
        
        return max(0, self.max_requests - recent_requests)
    
    def reset_user(self, user_id: int) -> None:
        """Reset rate limit for a user."""
        if user_id in self._requests:
            del self._requests[user_id]


# Global rate limiter instance
rate_limiter = RateLimiter(
    max_requests=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window
)


def with_rate_limit(
    handler: Callable
) -> Callable:
    """
    Decorator для применения rate limiting к handler.
    
    Args:
        handler: Handler function to wrap
        
    Returns:
        Wrapped handler function
    """
    @wraps(handler)
    async def wrapper(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        user = update.effective_user
        
        if not user:
            return await handler(update, context)
        
        # Check rate limit
        if not rate_limiter.is_allowed(user.id):
            remaining = rate_limiter.get_remaining_requests(user.id)
            msg = update.effective_message
            if msg:
                await msg.reply_text(
                    f"⚠️ Слишком много запросов. Пожалуйста, подождите немного.\n"
                    f"Доступно запросов: {remaining}/{settings.rate_limit_requests}"
                )
            return
        
        return await handler(update, context)
    
    return wrapper


def with_error_handler(
    handler: Callable
) -> Callable:
    """
    Decorator для обработки ошибок в handlers.
    
    Args:
        handler: Handler function to wrap
        
    Returns:
        Wrapped handler function with error handling
    """
    @wraps(handler)
    async def wrapper(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        try:
            return await handler(update, context)
            
        except Exception as e:
            logger.error(
                f"Error in handler {handler.__name__}: {e}",
                exc_info=True
            )
            
            # Try to notify user
            try:
                if update.effective_message:
                    await update.effective_message.reply_text(
                        "❌ Произошла ошибка. Попробуйте позже или обратитесь к администратору."
                    )
            except Exception as notify_error:
                logger.error(f"Failed to send error notification: {notify_error}")
            
            # Re-raise in debug mode
            if settings.debug:
                raise
    
    return wrapper


def with_logging(
    handler: Callable
) -> Callable:
    """
    Decorator для логирования вызовов handlers.
    
    Args:
        handler: Handler function to wrap
        
    Returns:
        Wrapped handler function with logging
    """
    @wraps(handler)
    async def wrapper(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        user = update.effective_user
        message = update.effective_message
        
        # Log incoming message
        if user and message:
            logger.info(
                f"Handler: {handler.__name__} | "
                f"User: {user.id} (@{user.username}) | "
                f"Message: {message.text[:50] if message.text else 'N/A'}..."
            )
        
        start_time = time.time()
        
        try:
            result = await handler(update, context)
            duration = time.time() - start_time
            
            logger.info(
                f"Handler {handler.__name__} completed in {duration:.2f}s"
            )
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Handler {handler.__name__} failed after {duration:.2f}s: {e}"
            )
            raise
    
    return wrapper


def with_middleware(
    handler: Callable
) -> Callable:
    """
    Decorator для применения всех middleware к handler.
    
    Применяет в порядке:
    1. Logging
    2. Error handling
    3. Rate limiting
    
    Args:
        handler: Handler function to wrap
        
    Returns:
        Fully wrapped handler function
    """
    return with_logging(with_error_handler(with_rate_limit(handler)))


class MetricsCollector:
    """
    Collector для метрик бота.
    
    Отслеживает:
    - Количество сообщений
    - Количество пользователей
    - Среднее время ответа
    - Ошибки
    """
    
    def __init__(self):
        """Initialize metrics collector."""
        self.message_count = 0
        self.user_ids = set()
        self.error_count = 0
        self.response_times: list[float] = []
        self.start_time = datetime.now()
    
    def record_message(self, user_id: int) -> None:
        """Record incoming message."""
        self.message_count += 1
        self.user_ids.add(user_id)
    
    def record_error(self) -> None:
        """Record error occurrence."""
        self.error_count += 1
    
    def record_response_time(self, duration: float) -> None:
        """Record handler response time."""
        self.response_times.append(duration)
        
        # Keep only last 1000 measurements
        if len(self.response_times) > 1000:
            self.response_times = self.response_times[-1000:]
    
    def get_stats(self) -> Dict:
        """
        Get current metrics.
        
        Returns:
            Dictionary with metrics
        """
        uptime = datetime.now() - self.start_time
        
        avg_response_time = (
            sum(self.response_times) / len(self.response_times)
            if self.response_times
            else 0
        )
        
        return {
            "uptime_seconds": uptime.total_seconds(),
            "message_count": self.message_count,
            "unique_users": len(self.user_ids),
            "error_count": self.error_count,
            "avg_response_time": avg_response_time,
            "messages_per_minute": (
                self.message_count / (uptime.total_seconds() / 60)
                if uptime.total_seconds() > 0
                else 0
            )
        }
    
    def format_stats(self) -> str:
        """Format stats for display."""
        stats = self.get_stats()
        
        uptime_str = str(timedelta(seconds=int(stats["uptime_seconds"])))
        
        return f"""📊 Статистика бота:

⏱ Uptime: {uptime_str}
💬 Сообщений: {stats['message_count']}
👥 Пользователей: {stats['unique_users']}
❌ Ошибок: {stats['error_count']}
⚡️ Среднее время ответа: {stats['avg_response_time']:.2f}s
📈 Сообщений/мин: {stats['messages_per_minute']:.2f}
"""


# Global metrics collector
metrics = MetricsCollector()


__all__ = [
    "with_middleware",
    "with_rate_limit",
    "with_error_handler",
    "with_logging",
    "rate_limiter",
    "metrics",
    "MetricsCollector",
    "RateLimiter",
]
