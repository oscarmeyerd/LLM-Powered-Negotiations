# This is the cooperative agent. It's goal is to ensure fair deals while meeting its own needs to maximize utility.

import asyncio
import logging
import random
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

# Dynamically assigning role...
import socket

def get_available_role():
    "Determine which BSPL role this agent should take"
    # Try AgentB first as it is preferred role, port 8011.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 8011))
        sock.close()
        return "AgentB", 1  # returning agentB role, color index 1
    except OSError:
        pass
    
    # Backup attempt to be AgentA, port 8010.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 8010))
        sock.close()
        return "AgentA", 0  # returning agentA role, color index 0
    except OSError:
        pass
    
    # Fallback to AgentB
    return "AgentB", 1

role_name, color_index = get_available_role()

# start adapter
adapter = Adapter(role_name, systems, agents, color=COLORS[color_index])
logger = logging.getLogger("cooperative_agent")
make_msg = instantiate(adapter)
stats = NegotiationStats()

# cooperative strategy params.
CONCESSION_RATE = 0.6 # Balanced concession rate
ACCEPTANCE_THRESHOLD = 0.5 # Balanced acceptance threshold.

def calculate_utility(gained, given):
    "Utility calculation for cooperative strategy"
    total_gain = sum(gained.values()) if gained else 0
    total_cost = sum(given.values()) if given else 0
    return total_gain - (total_cost * 0.7) + (min(total_gain, total_cost) * 0.3)

# action on proposal.
@adapter.reaction(propose)
async def on_propose(msg):
    "Handle proposals with LLM-powered cooperative decision making"
    try:
        logger.info("Received proposal from AgentA")
        stats.total_offers_received += 1
        
        # LLM-powered decision first
        try:
            context = {
                'resource_type': msg['resource_type'],
                'quantity': msg['quantity'],
                'offer_value': msg['offer_value'],
                'round': 1
            }
            
            prompt = get_negotiation_prompt("cooperative", "evaluate_proposal", context)
            logger.info(f"Asking LLM: {prompt[:100]}...")
            llm_response = await call_llm(prompt, "cooperative")
            
            if llm_response:
                logger.info(f"LLM Response: {llm_response}")
                decision_data = json.loads(llm_response)
                decision = decision_data.get('decision', 'REJECT')
                reason = decision_data.get('reason', 'LLM decision')
                confidence = decision_data.get('confidence', 0.5)
                
                logger.info(f"LLM Decision: {decision} (confidence: {confidence}) - {reason}")
                # acceptance from LLM
                if decision == 'ACCEPT':
                    response = make_msg(accept,
                                      ID=msg["ID"],
                                      resource_type=msg["resource_type"],
                                      quantity=msg["quantity"],
                                      counter_value=msg["offer_value"],
                                      utility_value=random.uniform(0.4, 0.7))
                    await adapter.send(response)
                    logger.info(f"LLM ACCEPTED proposal {msg['ID']}: {msg['offer_value']} - {reason}")
                    return
                else:
                    # rejection from LLM, creating a counter offer based on strategic parameters above.
                    counter_val = int(msg["offer_value"] * CONCESSION_RATE)
                    
                    response = make_msg(counter,
                                      ID=msg["ID"],
                                      resource_type=msg["resource_type"],
                                      quantity=msg["quantity"],
                                      counter_value=counter_val,
                                      negotiation_round=1)
                    # send counter
                    await adapter.send(response)
                    logger.info(f"LLM REJECTED, countering {msg['ID']}: {msg['offer_value']} -> {counter_val} - {reason}")
                    return
            else:
                logger.warning("LLM returned no response, using fallback")
        except Exception as e:
            logger.warning(f"LLM decision failed: {e}, using fallback counter-offer")
        
        # default if LLM fails.
        counter_val = int(msg["offer_value"] * CONCESSION_RATE)
        
        response = make_msg(counter,
                          ID=msg["ID"],
                          resource_type=msg["resource_type"],
                          quantity=msg["quantity"],
                          counter_value=counter_val,
                          negotiation_round=1)
        
        await adapter.send(response)
        logger.info(f"Countered proposal {msg['ID']}: {msg['offer_value']} -> {counter_val}")
        
    except Exception as e:
        logger.error(f"Error in proposal handler: {e}")
# acceptance reaction
@adapter.reaction(accept)
async def on_accept(msg):
    "Handle accept from AgentA - AgentB responds with final_accept"
    stats.successful_agreements += 1
    
    response = make_msg(final_accept,
                      ID=msg["ID"],
                      resource_type=msg["resource_type"],
                      quantity=msg["quantity"],
                      offer_value=msg["counter_value"],
                      utility_value=random.uniform(0.4, 0.7))
    await adapter.send(response)
    logger.info(f"Final accept: agreement reached for {msg['counter_value']}")
# rejection reaction
@adapter.reaction(reject)
async def on_reject(msg):
    "Handle reject from AgentA - AgentB responds with final_reject"
    
    response = make_msg(final_reject,
                      ID=msg["ID"],
                      resource_type=msg["resource_type"],
                      quantity=msg["quantity"],
                      offer_value=msg["counter_value"],
                      outcome="negotiation_failed")
    await adapter.send(response)
    logger.info(f"Final reject: negotiation {msg['ID']} failed")
# final acceptance
@adapter.reaction(final_accept) 
async def on_final_accept(msg):
    "Handle final acceptance"
    stats.successful_agreements += 1
    logger.info("Final cooperative agreement reached")
# end of negotiations
@adapter.reaction("session_end")
async def on_session_end(_msg):
    "Handle session end"
    logger.info(f"Negotiation session ended. Agreements: {stats.successful_agreements}")
    adapter.stop()
# proposal generator, same as seen in aggressive agent, but less frequent/morecooperative
async def proposal_generator():
    "Background task to generate proposals"
    negotiation_counter = 0
    
    await asyncio.sleep(5)  # Let other agents start first
    logger.info("Cooperative proposal generator starting")
    
    try:
        while True:
            await asyncio.sleep(random.uniform(8, 12))  # Cooperative timing - less frequent
            
            negotiation_counter += 1
            
            try:
                ID = str(uuid.uuid4())
                
                # Try LLM-powered proposal generation
                try:
                    context = {'round': negotiation_counter}
                    prompt = get_negotiation_prompt("cooperative", "generate_proposal", context)
                    llm_response = await call_llm(prompt, "cooperative")
                    
                    if llm_response:
                        proposal_data = json.loads(llm_response)
                        resource_type = proposal_data.get('resource_type', 'computing_cycles')
                        quantity = proposal_data.get('quantity', random.randint(15, 35))
                        offer_value = proposal_data.get('offer_value', random.randint(80, 150))
                        reasoning = proposal_data.get('reasoning', 'LLM generated')
                        
                        logger.info(f"LLM cooperative proposal {negotiation_counter}: {quantity} {resource_type} for {offer_value} - {reasoning}")
                    else:
                        raise Exception("No LLM response")
                        
                except Exception as e:
                    logger.warning(f"LLM proposal generation failed: {e}, using fallback")
                    resource_type = "computing_cycles"
                    quantity = random.randint(15, 35)
                    offer_value = random.randint(80, 150)
                    logger.info(f"Fallback cooperative proposal {negotiation_counter}: {quantity} {resource_type} for {offer_value}")
                
                msg = make_msg(propose, 
                    ID=ID,
                    resource_type=resource_type,
                    quantity=quantity,
                    offer_value=offer_value
                )
                
                await adapter.send(msg)
                logger.info(f"Sent cooperative proposal {negotiation_counter}")
                stats.total_negotiations += 1
                
            except Exception as e:
                logger.error(f"Failed to send proposal: {e}")
                
    except asyncio.CancelledError:
        logger.info(f"Cooperative agent stopped. Final agreements: {stats.successful_agreements}")
        raise
# main
async def main():
    "Main execution - AgentB can both send and receive proposals"
    logger.info("Cooperative Agent starting")
    logger.info("Agent can both send and receive proposals...")
    
    # Starting proposal generator
    asyncio.create_task(proposal_generator())
    # sleep before ending main
    await asyncio.sleep(0.1)
# entry point
if __name__ == "__main__":
    try:
        logger.info("Starting Cooperative Agent (AgentB)...")
        adapter.start(main())
    except KeyboardInterrupt:
        logger.info("Agent stopped")
    except Exception as e:
        logger.error(f"Agent error: {e}")