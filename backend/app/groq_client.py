from groq import Groq

from .config import settings

groq_client = Groq(api_key=settings.groq_api_key)
