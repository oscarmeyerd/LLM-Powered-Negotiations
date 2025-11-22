# LLM behavior and interactions for each agent type.

import os
import random
import asyncio
import logging
import aiohttp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("llm")
_llm_lock = asyncio.Semaphore(1)
# role to env
ROLE_ENV_MAP = {
    "aggressive": ("OPENROUTER_API_KEY_AGGRESSIVE", "OPENROUTER_MODEL_AGGRESSIVE"),
    "cooperative": ("OPENROUTER_API_KEY_COOPERATIVE", "OPENROUTER_MODEL_COOPERATIVE"),
    "gradual": ("OPENROUTER_API_KEY_GRADUAL", "OPENROUTER_MODEL_GRADUAL"),
}

# default LLM model
DEFAULT_MODEL = "meta-llama/llama-3.2-3b-instruct:free"

# Calling LLM
async def call_llm(full_user_prompt: str, role: str = "aggressive", retries: int = 5) -> str:
    "Asynchronous call to OpenRouter LLM API per-agent with robust error handling."
    key_var, model_var = ROLE_ENV_MAP.get(role, ("OPENROUTER_API_KEY", "OPENROUTER_MODEL"))
    api_key = os.getenv(key_var) or os.getenv("OPENROUTER_API_KEY")
    model = os.getenv(model_var) or os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL
    # API error handling
    if not api_key:
        logger.error(f"[{role}] No API key found in environment for {key_var}.")
        return None
    # headers for API call
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv("HTTP_REFERER", "http://localhost"),
        "X-Title": os.getenv("OPENROUTER_TITLE", "BSPL_Agent_Network"),
    }
    # quick system prompt
    system_prompt = (
        "You are a negotiating agent participating in a multi-agent system. Your role is to make decisions about proposals, counter-offers, and negotiations. Respond succinctly only in valid JSON."
    )
    # construct payload
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_user_prompt},
        ],
        "temperature": 0.3,
    }

    url = "https://openrouter.ai/api/v1/chat/completions"
    # llm call with retries & error handling
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
                            logger.warning(f"[{role}] Rate limited by LLM. Retrying in {wait_time:.1f}s...")
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

        logger.error(f"[{role}] Exceeded maximum retries for LLM.")
        return None

# Prompts. One information block, each agent type has varying prompts for completing proposals, evaluating offers, and making counter offers. The agents pull independently from this block based on their assigned role.
def get_negotiation_prompt(agent_type: str, action: str, context: dict) -> str:
    "Generate role-specific prompts for different negotiation actions."
    
    base_context = f"""
Current negotiation context:
- Resource: {context.get('resource_type', 'computing_cycles')}
- Quantity: {context.get('quantity', 0)}
- Offer value: {context.get('offer_value', 0)}
- Negotiation round: {context.get('round', 1)}
"""
    
    if agent_type == "aggressive":
        if action == "evaluate_proposal":
            offer_val = context.get('offer_value', 0)
            return f"""{base_context}
As an AGGRESSIVE negotiator, you prioritize quick deals but you're not stupid about value.

CRITICAL: The offer value is {offer_val}. You must do simple math:
- If {offer_val} ≥ 50: You can ACCEPT (reasonable for quick deals)
- If {offer_val} < 50: You should COUNTER (make a better offer to keep negotiating)

Mathematical check:
- Offer value: {offer_val}
- Minimum threshold: 50
- Is {offer_val} ≥ 50? {"YES" if offer_val >= 50 else "NO"}
- Therefore: {"ACCEPT" if offer_val >= 50 else "COUNTER"}

Your decision MUST match the math above. Do not ignore these numbers.

Respond in JSON format:
{{"decision": "{"ACCEPT" if offer_val >= 50 else "COUNTER"}", "reason": "Value {offer_val} is {"≥" if offer_val >= 50 else "<"} 50 threshold", "confidence": 0.9}}"""
        
        elif action == "generate_proposal":
            return f"""{base_context}

As an AGGRESSIVE negotiator, generate a new proposal that aims for quick agreement.
This means that you should make reasonable offers that are likely to be accepted quickly by your opposing agent.

Generate a proposal considering:
- Offer VERY competitive values to encourage acceptance
- Your needs are less important than closing the deal quickly, with priority on speed. Still pay mind that you do not LOSE value on a deal. You still want to ensure some value gain.
- Aim for 70-80% of ideal value to ensure quick agreement

Respond in JSON format:
{{"resource_type": "computing_cycles", "quantity": 10-40, "offer_value": 80-200, "reasoning": "brief explanation"}}"""

    if agent_type == "cooperative":
        if action == "evaluate_proposal":
            offer_val = context.get('offer_value', 0)
            return f"""{base_context}

As a COOPERATIVE negotiator, you seek fair deals but you're not naive about value.

MATHEMATICAL ANALYSIS - The offer value is {offer_val}:
- If {offer_val} ≥ 80: You can ACCEPT (fair value for cooperation)
- If {offer_val} < 80: You should COUNTER (make a fair counter-offer to continue cooperating)

Mathematical check:
- Offer value: {offer_val}
- Minimum threshold: 80
- Is {offer_val} ≥ 80? {"YES" if offer_val >= 80 else "NO"}
- Therefore: {"ACCEPT" if offer_val >= 80 else "COUNTER"}

Your decision MUST match this mathematical analysis.

Respond in JSON format:
{{"decision": "{"ACCEPT" if offer_val >= 80 else "COUNTER"}", "reason": "Value {offer_val} is {"≥" if offer_val >= 80 else "<"} 80 cooperative threshold", "confidence": 0.9}}"""
        
        elif action == "generate_proposal":
            return f"""{base_context}

As a COOPERATIVE negotiator, generate a fair proposal that balances both parties' interests.
Your strategy: Make reasonable offers that provide good value to you while being fair to your opponent.

Generate a proposal considering:
- Fair value exchange for both parties
- Building trust through reasonable offers
- Aim for 75-85% of your ideal value while leaving room for opponent profit

Respond in JSON format:
{{"resource_type": "computing_cycles", "quantity": 15-35, "offer_value": 100-180, "reasoning": "brief explanation"}}"""

    elif agent_type == "gradual":
        if action == "evaluate_proposal":
            offer_val = context.get('offer_value', 0)
            round_num = context.get('round', 1)
            min_threshold = max(50, 100 - (round_num * 15))  # Starts at 100, decreases by 15 per round, min 50
            return f"""{base_context}

As a GRADUAL negotiator, you have high standards that gradually lower over time.

ROUND {round_num} ANALYSIS - The offer value is {offer_val}:
- Round {round_num} minimum threshold: {min_threshold}
- If {offer_val} ≥ {min_threshold}: You can ACCEPT
- If {offer_val} < {min_threshold}: You should COUNTER (make a strategic counter-offer)

Mathematical check:
- Offer value: {offer_val}
- Round {round_num} threshold: {min_threshold}
- Is {offer_val} ≥ {min_threshold}? {"YES" if offer_val >= min_threshold else "NO"}
- Therefore: {"ACCEPT" if offer_val >= min_threshold else "COUNTER"}

Your decision MUST match this mathematical calculation.

Respond in JSON format:
{{"decision": "{"ACCEPT" if offer_val >= min_threshold else "COUNTER"}", "reason": "Round {round_num}: Value {offer_val} is {"≥" if offer_val >= min_threshold else "<"} threshold {min_threshold}", "confidence": 0.9}}"""
        
        elif action == "generate_proposal":
            return f"""{base_context}

As a GRADUAL negotiator, your proposals should lead to high-value deals over time, while still maintaining reasonableness as not to immediately face rejection.
You should aim to start with strong initial proposals that would yield high returns, while still being reasonable enough to maintain negotiations. Small concessions over time can be made as counteroffers are exchanged. As the rounds progress, you may lower your goal values slightly to ensure agreements are made.

Generate a proposal considering:
- Start with high-value offers, making small concessions over time
- Aim to test the limits of your opponent's willingness to pay.
- Aim for 85-95% of ideal value initially, accepting gradual concessions

Respond in JSON format:
{{"resource_type": "computing_cycles", "quantity": 10-30, "offer_value": 120-250, "reasoning": "brief explanation"}}"""

    return f"{base_context}\nAs a {agent_type} negotiator, make a strategic decision for action: {action}"