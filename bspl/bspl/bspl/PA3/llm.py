import os
import random
import asyncio
import logging
import aiohttp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("llm")
_llm_lock = asyncio.Semaphore(1)

ROLE_ENV_MAP = {
    "buyer": ("OPENROUTER_API_KEY_BUYER", "OPENROUTER_MODEL_BUYER"),
    "seller": ("OPENROUTER_API_KEY_SELLER", "OPENROUTER_MODEL_SELLER"),
    "shipper": ("OPENROUTER_API_KEY_SHIPPER", "OPENROUTER_MODEL_SHIPPER"),
}

DEFAULT_MODEL = "minimax/minimax-m2:free"


async def call_llm(full_user_prompt: str, role: str = "buyer", retries: int = 5) -> str:
    """Asynchronous call to OpenRouter LLM API per-agent with robust error handling."""
    key_var, model_var = ROLE_ENV_MAP.get(role, ("OPENROUTER_API_KEY", "OPENROUTER_MODEL"))
    api_key = os.getenv(key_var) or os.getenv("OPENROUTER_API_KEY")
    model = os.getenv(model_var) or os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL

    if not api_key:
        logger.error(f"[{role}] No API key found in environment for {key_var}.")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv("HTTP_REFERER", "http://localhost"),
        "X-Title": os.getenv("OPENROUTER_TITLE", "BSPL_Agent_Network"),
    }

    system_prompt = (
        "You are an intelligent autonomous agent participating in a multi-agent system. "
        "Respond concisely and always in valid JSON when instructed."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_user_prompt},
        ],
        "temperature": 0.3,
    }

    url = "https://openrouter.ai/api/v1/chat/completions"

    async with _llm_lock:
        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, json=payload, timeout=45) as resp:
                        text = await resp.text()
                        if resp.status == 200:
                            try:
                                data = await resp.json()
                            except Exception:
                                logger.error(f"[{role}] Failed to parse LLM JSON: {text[:200]}")
                                return None

                            if "choices" in data and data["choices"]:
                                content = data["choices"][0]["message"]["content"]
                                return (
                                    content.strip()
                                    .removeprefix("```json")
                                    .removeprefix("```")
                                    .removesuffix("```")
                                    .strip()
                                )
                            else:
                                err_msg = data.get("error", {}).get("message", "Malformed LLM response.")
                                logger.warning(f"[{role}] No 'choices' key in LLM response. Error: {err_msg}")
                                return None

                        elif resp.status == 429:
                            wait_time = (2 ** attempt) + random.uniform(2, 4)
                            logger.warning(f"[{role}] Rate limited by LLM API. Retrying in {wait_time:.1f}s...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"[{role}] LLM API error {resp.status}: {text[:200]}")
                            return None

            except asyncio.TimeoutError:
                wait_time = (2 ** attempt) + random.uniform(1, 3)
                logger.warning(f"[{role}] Timeout. Retrying in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
            except aiohttp.ClientError as e:
                wait_time = (2 ** attempt) + random.uniform(1, 3)
                logger.error(f"[{role}] Connection error: {e}. Retrying in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"[{role}] Unexpected LLM error: {e}")
                return None

        logger.error(f"[{role}] Exceeded maximum retries for LLM API.")
        return None
