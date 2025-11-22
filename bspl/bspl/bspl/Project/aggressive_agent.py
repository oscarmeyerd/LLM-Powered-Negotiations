# This is the aggressive agent - its goal is to prioritize FAST deals with high concession rates. LLM integration allows intelligent proposal generation and evaluations. The aggressive agent will close deals quickly while maintaining some value gain - MORE deals is the end goal
# in order to maximize successful negotiations and value gain.

import asyncio
import logging
import random
from typing import Dict
import uuid
import socket
import json

from bspl.adapter import Adapter
from bspl.adapter.core import COLORS
from configuration import systems, agents
from bspl.adapter.schema import instantiate
from metrics import NegotiationStats
from llm import call_llm, get_negotiation_prompt

from Negotiation import propose, counter, accept, reject, final_accept, final_reject

# Needed for dynamic role assignment to allow the aggressive agent to propose deals or respond to deals (AgentA or AgentB).
import socket

def get_available_role():
    "Determine which BSPL role this agent should take"
    # Trying agentA (port 8010) as it is the preferred role for the aggressive agent.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 8010))
        sock.close()
        return "AgentA", 0  # AgentA role, color index 0
    except OSError:
        pass
    
    # Trying agentB (port 8011) as the secondary role for the aggressive agent.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 8011))
        sock.close()
        return "AgentB", 1  # AgentB role, color index 1
    except OSError:
        pass
    
    # Fallback to AgentA
    return "AgentA", 0

role_name, color_index = get_available_role()

# Starting the adapter based on role determined.
adapter = Adapter(role_name, systems, agents, color=COLORS[color_index])
logger = logging.getLogger("aggressive_agent")
make_msg = instantiate(adapter)
stats = NegotiationStats()

# Hard coded paramters for aggressive deal making strategy.
CONCESSION_RATE = 0.8 # Quick acceptance, high concessions.
ACCEPTANCE_THRESHOLD = 0.3 #Low utility threshold for faster deals.
MAX_ROUNDS = 3 # Max rounds before acceptance is forced.

# Utility calculation. Used to evaluate offers. Written with aggressive strategy in mind.
def calculate_utility(gained: Dict[str, int], given: Dict[str, int]) -> float:
    "Utility calculation for aggressive strategy"
    total_gain = sum(gained.values())
    total_cost = sum(given.values())
    return max(0.1, total_gain - (total_cost * 0.5))

# Counter offer handling.
@adapter.reaction(counter)
async def on_counter(msg):
    "Handle counters from AgentB with LLM decision making"
    stats.total_offers_received += 1
    
    # LLM decision.
    try:
        context = {
            'resource_type': msg['resource_type'],
            'quantity': msg['quantity'],
            'offer_value': msg['counter_value'],
            'round': 1
        }
        # Grabbing prompt to evaluate the offer.
        prompt = get_negotiation_prompt("aggressive", "evaluate_proposal", context)
        logger.info(f"Asking LLM: {prompt[:100]}...")
        llm_response = await call_llm(prompt, "aggressive")
        
        #Loop for LLM response breakdown.
        if llm_response:
            logger.info(f"LLM Response: {llm_response}")
            decision_data = json.loads(llm_response)
            decision = decision_data.get('decision', 'REJECT')
            reason = decision_data.get('reason', 'LLM decision')
            confidence = decision_data.get('confidence', 0.5)
            
            logger.info(f"LLM Decision: {decision} (confidence: {confidence}) - {reason}")
            # Storing stats based on acctept.
            if decision == 'ACCEPT':
                stats.successful_agreements += 1
                response = make_msg(accept,
                              ID=msg["ID"],
                              resource_type=msg["resource_type"],
                              quantity=msg["quantity"],
                              counter_value=msg["counter_value"],
                              utility_value=random.uniform(0.3, 0.8))
                await adapter.send(response)
                logger.info(f"LLM ACCEPTED counter: {msg['counter_value']} - {reason}")
                return
            else: # Storing stats based on reject.
                response = make_msg(reject,
                              ID=msg["ID"],
                              resource_type=msg["resource_type"],
                              quantity=msg["quantity"],
                              counter_value=msg["counter_value"],
                              outcome="rejected")
                await adapter.send(response)
                logger.info(f"LLM REJECTED counter: {msg['counter_value']} - {reason}")
                return
        else:
            logger.warning("LLM returned no response, using fallback")
    except Exception as e:
        logger.warning(f"LLM decision failed: {e}, using fallback logic")
    
    # Default logic in case LLM failure - value-aware fallback
    offer_value = msg.get("counter_value", msg.get("offer_value", 0))
    
    # Aggressive but rejects offers that are too low.
    if offer_value >= 30:  # Minimum acceptable value for aggressive agent
        stats.successful_agreements += 1
        response = make_msg(accept,
                          ID=msg["ID"],
                          resource_type=msg["resource_type"],
                          quantity=msg["quantity"],
                          counter_value=msg["counter_value"],
                          utility_value=random.uniform(0.3, 0.8))
        await adapter.send(response)
        logger.info(f"ACCEPTED counter: {msg['counter_value']} (fallback - value {offer_value} >= 30)")
    else:
        response = make_msg(reject,
                          ID=msg["ID"],
                          resource_type=msg["resource_type"],
                          quantity=msg["quantity"],
                          counter_value=msg["counter_value"],
                          outcome="rejected")
        await adapter.send(response)
        logger.info(f"REJECTED counter: {msg['counter_value']} (fallback - value {offer_value} < 30)")
# Final acceptance handling.
@adapter.reaction("final_accept")
async def on_final_accept(msg):
    "Handle final acceptance from AgentB"
    stats.successful_agreements += 1
    logger.info("AgentB accepted proposal")
# Final rejection handling.
@adapter.reaction("final_reject")
async def on_final_reject(msg):
    "Handle final rejection from AgentB"
    logger.info("AgentB rejected proposal")
# Acceptance handling.
@adapter.reaction(accept)
async def on_accept(msg):
    "Handle acceptance"
    stats.successful_agreements += 1
    logger.info("Offer accepted")
# Rejection handling.
@adapter.reaction(reject)
async def on_reject(msg):
    "Handle rejections with quick counter-offers"
    logger.info("Offer rejected - making quick counter-offer")
    
    # counter lower
    try:
        # Aggressive agents make quick concessions
        original_value = msg.get("counter_value", msg.get("offer_value", 100))
        counter_value = int(original_value * 0.85)  # Quick 15% concession
        
        resource_type = msg.get("resource_type", "computing_cycles")
        quantity = msg.get("quantity", random.randint(20, 40))
        
        logger.info(f"Quick counter after rejection: {quantity} {resource_type} for {counter_value}")
        
        # Generate counter
        proposal = make_msg(propose,
                           ID=f"aggressive_{random.randint(1000, 9999)}",
                           resource_type=resource_type,
                           quantity=quantity,
                           offer_value=counter_value,
                           negotiation_round=1)
        
        await adapter.send(proposal)
        logger.info("Aggressive counter-offer sent to keep negotiation alive")
        
    except Exception as e:
        logger.warning(f"Failed to generate counter-offer: {e}")
        logger.info("Moving on to next opportunity")
# End of negotiation.
@adapter.reaction("session_end")
async def on_session_end(_msg):
    "Session cleanup"
    logger.info(f"Negotiation session ended. Agreements: {stats.successful_agreements}")
    adapter.stop()
# Loop to generate prroposals.
async def proposal_generator():
    "Background task to generate proposals"
    negotiation_counter = 0
    
    await asyncio.sleep(3)
    logger.info("Proposal generator starting")
    
    try:
        while True:
            await asyncio.sleep(random.uniform(3, 7))
            
            negotiation_counter += 1
            
            try:
                ID = str(uuid.uuid4())
                
                # LLM-powered proposal generation
                try:
                    context = {'round': negotiation_counter}
                    prompt = get_negotiation_prompt("aggressive", "generate_proposal", context)
                    llm_response = await call_llm(prompt, "aggressive")
                    
                    if llm_response:
                        proposal_data = json.loads(llm_response)
                        resource_type = proposal_data.get('resource_type', 'computing_cycles')
                        quantity = proposal_data.get('quantity', random.randint(20, 40))
                        offer_value = proposal_data.get('offer_value', random.randint(100, 200))
                        reasoning = proposal_data.get('reasoning', 'LLM generated')
                        
                        logger.info(f"LLM proposal {negotiation_counter}: {quantity} {resource_type} for {offer_value} - {reasoning}")
                    else:
                        raise Exception("No LLM response")
                # Exception fallback in the case the LLM fails.
                except Exception as e:
                    logger.warning(f"LLM proposal generation failed: {e}, using fallback")
                    resource_type = "computing_cycles"
                    quantity = random.randint(20, 40)
                    offer_value = random.randint(100, 200)
                    logger.info(f"Fallback proposal {negotiation_counter}: {quantity} {resource_type} for {offer_value}")
                # Proposal message creation.
                msg = make_msg(propose, 
                    ID=ID,
                    resource_type=resource_type,
                    quantity=quantity,
                    offer_value=offer_value
                )
                # Send proposal.
                await adapter.send(msg)
                logger.info(f"Sent proposal {negotiation_counter}")
                stats.total_negotiations += 1
            # Case where proposal sending fails.
            except Exception as e:
                logger.error(f"Failed to send proposal: {e}")
    # Handles cancellation of generator.     
    except asyncio.CancelledError:
        logger.info(f"Agent stopped. Final agreements: {stats.successful_agreements}")
        raise
# Main
async def main():
    "Main execution - AgentA initiates negotiations"
    logger.info("Aggressive Agent starting")
    logger.info("Agent will initiate negotiations...")
    
    asyncio.create_task(proposal_generator())
    await asyncio.sleep(0.1)
# entry point.
if __name__ == "__main__":
    try:
        logger.info("Starting Aggressive Agent (AgentA)...")
        adapter.start(main())
    except KeyboardInterrupt:
        logger.info("Agent stopped")
    except Exception as e:
        logger.error(f"Agent error: {e}")