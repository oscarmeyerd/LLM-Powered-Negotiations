# Gradual agent, prioritizes patience and making strategic concessions to MAXIMIZE utility over time. It cares only about gaining the most value possible.

import asyncio
import logging
import random
import json

from bspl.adapter import Adapter
from bspl.adapter.core import COLORS
from configuration import systems, agents
from bspl.adapter.schema import instantiate
from metrics import NegotiationStats
from llm import call_llm, get_negotiation_prompt

from Negotiation import propose, counter, accept, reject, final_accept, final_reject

# same dynamic role assignment as seen in other agents.
import socket

def get_available_role():
    "Determine which BSPL role this agent should take"
    # Trying AgentA first (port 8010)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 8010))
        sock.close()
        return "AgentA", 0  
    except OSError:
        pass
    
    # AgentB attempt
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('127.0.0.1', 8011))
        sock.close()
        return "AgentB", 1 
    except OSError:
        pass
    
    # Fallback to AgentA with different port to avoid conflict with other agents.
    return "AgentA", 2

role_name, color_index = get_available_role()

# starting the adapter and stats
adapter = Adapter(role_name, systems, agents, color=COLORS[color_index])
logger = logging.getLogger("gradual_agent")
make_msg = instantiate(adapter)
stats = NegotiationStats()

# Params for a gradual strategy. 
CONCESSION_RATE = 0.4 # Concession rate lower to indicate patience.
ACCEPTANCE_THRESHOLD = 0.7 # Acceptance threshold higher (selective)
PATIENCE_ROUNDS = 3 # Number of rounds to wait before conceding

# Resource ranges (used to normalize offer_value into [0,1])
RESOURCE_RANGES = {
    "computing_cycles": (1, 100),
    "data_storage": (1, 500),
    "network_bandwidth": (1, 100),
    "processing_time": (1, 50),
}

# precompute maximum total for normalization
MAX_TOTAL = sum(r[1] for r in RESOURCE_RANGES.values())

# Track negotiation rounds for gradual strategy (want to lower expectations as rounds progress)
negotiation_rounds = {}

def calculate_utility(gained, given):
    "Utility calculation for gradual strategy"
    total_gain = sum(gained.values()) if gained else 0
    total_cost = sum(given.values()) if given else 0
    return total_gain - (total_cost * 1.2)
# reaction on proposal
@adapter.reaction(propose)
async def on_propose(msg):
    "Handle proposals with strategic patience and LLM decision-making"
    stats.total_offers_received += 1
    neg_id = msg["ID"]
    # tracking rounds
    if neg_id not in negotiation_rounds:
        negotiation_rounds[neg_id] = 0
    negotiation_rounds[neg_id] += 1
    
    # LLM decision first
    try:
        context = {
            "resource_type": msg["resource_type"],
            "quantity": msg["quantity"],
            "offer_value": msg["offer_value"],
            "round": negotiation_rounds[neg_id],
            "patience_threshold": PATIENCE_ROUNDS
        }
        
        llm_prompt = get_negotiation_prompt("gradual", "evaluate_proposal", context)
        logger.info("Gradual agent thinking about proposal...")
        
        llm_response = await call_llm(llm_prompt)
        # processing LLM response
        if llm_response:
            try:
                decision = json.loads(llm_response)
                if decision.get("action") == "accept":
                    # Verify that accepting meets the agent's own utility threshold
                    offer_value = msg.get("offer_value", 0)
                    human_norm = float(offer_value) / float(MAX_TOTAL) if MAX_TOTAL > 0 else 0.0
                    agent_util = max(0.0, 1.0 - human_norm)
                    logger.info(f"LLM suggests accept, computed agent_util={agent_util:.2f}")
                    if agent_util >= ACCEPTANCE_THRESHOLD:
                        logger.info("Accepting because agent utility meets threshold")
                        stats.successful_agreements += 1
                        response = make_msg(accept, 
                                          ID=msg["ID"],
                                          resource_type=msg["resource_type"],
                                          quantity=msg["quantity"],
                                          counter_value=msg["offer_value"],
                                          utility_value=decision.get("utility", agent_util))
                        await adapter.send(response)
                        logger.info(f"Strategic LLM accept after {negotiation_rounds[neg_id]} rounds")
                        return
                    else:
                        logger.info("LLM suggested accept but agent utility too low; issuing counter instead")
                elif decision.get("action") == "counter":
                    counter_val = decision.get("counter_value", int(msg["offer_value"] * CONCESSION_RATE))
                    logger.info(f"LLM decides to counter with {counter_val}")
                    response = make_msg(counter,
                                      ID=msg["ID"],
                                      resource_type=msg["resource_type"],
                                      quantity=msg["quantity"],
                                      counter_value=counter_val,
                                      negotiation_round=negotiation_rounds[neg_id])
                    await adapter.send(response)
                    logger.info(f"Strategic LLM counter: {counter_val} (round {negotiation_rounds[neg_id]})")
                    return
            except:
                logger.info("Failed to parse LLM response, using fallback")
    except Exception as e:
        logger.info(f"LLM call failed: {e}, using fallback")
    
    # Fallback to hard coded logic if LLM fails
    offer_value = msg.get("offer_value", 0)
    
    # Gradual agents have high standards but become more flexible over time
    min_acceptable = 80 - (negotiation_rounds[neg_id] * 10)  # Starts at 80, decreases by 10 per round
    
    # Compute agent utility from scalar offer_value and accept only if agent utility meets threshold
    human_norm = float(offer_value) / float(MAX_TOTAL) if MAX_TOTAL > 0 else 0.0
    agent_util = max(0.0, 1.0 - human_norm)
    if offer_value >= min_acceptable and agent_util >= ACCEPTANCE_THRESHOLD:
        stats.successful_agreements += 1
        response = make_msg(accept, 
                          ID=msg["ID"],
                          resource_type=msg["resource_type"],
                          quantity=msg["quantity"],
                          counter_value=msg["offer_value"],
                          utility_value=random.uniform(0.6, 0.9))
        await adapter.send(response)
        logger.info(f"Strategic accept: value {offer_value} >= {min_acceptable} and agent_util {agent_util:.2f} >= {ACCEPTANCE_THRESHOLD} (round {negotiation_rounds[neg_id]})")
    else:
        counter_val = int(msg["offer_value"] * CONCESSION_RATE)
        response = make_msg(counter,
                          ID=msg["ID"],
                          resource_type=msg["resource_type"],
                          quantity=msg["quantity"],
                          counter_value=counter_val,
                          negotiation_round=negotiation_rounds[neg_id])
        await adapter.send(response)
        logger.info(f"Strategic counter: {counter_val} (value {offer_value} < {min_acceptable}, round {negotiation_rounds[neg_id]})")
# reaction on a counter offer
@adapter.reaction(counter)
async def on_counter(msg):
    "Handle counters with strategic evaluation and LLM decision-making"
    stats.total_offers_received += 1
    neg_id = msg["ID"]
    
    if neg_id not in negotiation_rounds:
        negotiation_rounds[neg_id] = 0
    negotiation_rounds[neg_id] += 1
    
    # LLM decision first
    try:
        context = {
            "resource_type": msg["resource_type"],
            "quantity": msg["quantity"],
            "offer_value": msg["counter_value"],
            "round": negotiation_rounds[neg_id],
            "patience_threshold": PATIENCE_ROUNDS
        }
        
        llm_prompt = get_negotiation_prompt("gradual", "evaluate_proposal", context)
        logger.info("Gradual agent evaluating counter-offer...")
        
        llm_response = await call_llm(llm_prompt)
        # parsing LLM response
        if llm_response:
            try:
                decision = json.loads(llm_response)
                if decision.get("action") == "accept":
                    # Verify that accepting meets the agent's own utility threshold
                    counter_value = msg.get("counter_value", 0)
                    human_norm = float(counter_value) / float(MAX_TOTAL) if MAX_TOTAL > 0 else 0.0
                    agent_util = max(0.0, 1.0 - human_norm)
                    logger.info(f"LLM suggests accept counter, computed agent_util={agent_util:.2f}")
                    if agent_util >= ACCEPTANCE_THRESHOLD:
                        logger.info("Accepting counter because agent utility meets threshold")
                        stats.successful_agreements += 1
                        response = make_msg(accept,
                                          ID=msg["ID"],
                                          resource_type=msg["resource_type"],
                                          quantity=msg["quantity"],
                                          counter_value=msg["counter_value"],
                                          utility_value=decision.get("utility", agent_util))
                        await adapter.send(response)
                        logger.info(f"Strategic LLM accept after {negotiation_rounds[neg_id]} rounds")
                        return
                    else:
                        logger.info("LLM suggested accept but agent utility too low; rejecting counter")
            except:
                logger.info("Failed to parse LLM response, using fallback")
    except Exception as e:
        logger.info(f"LLM call failed: {e}, using fallback")
    
    # Fallback to hard coded logic if LLM fails - value-aware counter-offer evaluation
    counter_value = msg.get("counter_value", 0)
    
    # Gradual agents have high standards for counter-offers too
    min_acceptable = 80 - (negotiation_rounds[neg_id] * 10)  # Same logic as proposals
    
    # Compute agent utility and check threshold
    human_norm = float(counter_value) / float(MAX_TOTAL) if MAX_TOTAL > 0 else 0.0
    agent_util = max(0.0, 1.0 - human_norm)
    
    if counter_value >= min_acceptable and agent_util >= ACCEPTANCE_THRESHOLD:
        stats.successful_agreements += 1
        response = make_msg(accept,
                          ID=msg["ID"],
                          resource_type=msg["resource_type"],
                          quantity=msg["quantity"],
                          counter_value=msg["counter_value"],
                          utility_value=random.uniform(0.5, 0.8))
        await adapter.send(response)
        logger.info(f"Strategic accept: counter {counter_value} >= {min_acceptable} and agent_util {agent_util:.2f} >= {ACCEPTANCE_THRESHOLD} (round {negotiation_rounds[neg_id]})")
    else:
        # Send explicit reject message instead of silently doing nothing
        response = make_msg(reject,
                          ID=msg["ID"],
                          resource_type=msg["resource_type"],
                          quantity=msg["quantity"],
                          counter_value=msg["counter_value"],
                          outcome="rejected")
        await adapter.send(response)
        logger.info(f"Strategic rejection: counter {counter_value} (min_acceptable={min_acceptable}, agent_util={agent_util:.2f} < {ACCEPTANCE_THRESHOLD}, round {negotiation_rounds[neg_id]})")
# Acceptance
@adapter.reaction(accept)
async def on_accept(msg):
    "Handle acceptance of strategic offers"
    stats.successful_agreements += 1
    logger.info("Strategic patience paid off")
# Rejection
@adapter.reaction(reject)
async def on_reject(msg):
    "Handle rejections strategically with counter-offers"
    logger.info("Offer rejected - adjusting strategy")
    
    neg_id = msg["ID"]
    if neg_id not in negotiation_rounds:
        negotiation_rounds[neg_id] = 0
    negotiation_rounds[neg_id] += 1
    
    # counter proposal on rejection
    try:
        context = {
            "resource_type": msg.get("resource_type", "computing_cycles"),
            "quantity": msg.get("quantity", 20),
            "offer_value": msg.get("counter_value", 150),
            "round": negotiation_rounds[neg_id],
            "patience_threshold": PATIENCE_ROUNDS
        }
        
        llm_prompt = get_negotiation_prompt("gradual", "generate_proposal", context)
        logger.info("Gradual agent generating counter-proposal after rejection...")
        
        llm_response = await call_llm(llm_prompt, "gradual")
        
        if llm_response:
            try:
                proposal_data = json.loads(llm_response)
                resource_type = proposal_data.get('resource_type', 'computing_cycles')
                quantity = proposal_data.get('quantity', random.randint(15, 30))
                offer_value = proposal_data.get('offer_value', random.randint(120, 200))
                reasoning = proposal_data.get('reasoning', 'Strategic counter after rejection')
                
                logger.info(f"LLM counter-proposal: {quantity} {resource_type} for {offer_value} - {reasoning}")
            except Exception:
                raise Exception("Failed to parse LLM response")
        else:
            raise Exception("No LLM response")
                
    except Exception as e:
        logger.warning(f"LLM counter-proposal failed: {e}, using strategic fallback")
        resource_type = "computing_cycles"
        quantity = random.randint(15, 30)
        # Strategic adjustment - slightly lower offer after rejection
        offer_value = random.randint(120, 180)
        logger.info(f"Strategic counter after rejection: {quantity} {resource_type} for {offer_value}")
    
    # Generate counter-proposal message
    proposal = make_msg(propose,
                       ID=f"gradual_{random.randint(1000, 9999)}",
                       resource_type=resource_type,
                       quantity=quantity,
                       offer_value=offer_value,
                       negotiation_round=negotiation_rounds[neg_id])
    
    await adapter.send(proposal)
    logger.info(f"Strategic counter-proposal sent after rejection (round {negotiation_rounds[neg_id]})")
# Final acceptance
@adapter.reaction(final_accept)
async def on_final_accept(msg):
    "Handle final acceptance"
    stats.successful_agreements += 1
    logger.info("Strategic negotiation completed")
# End of negotiations.
@adapter.reaction("session_end")
async def on_session_end(_msg):
    "Handle session end"
    logger.info(f"Negotiation session ended. Results: {stats.successful_agreements}")
    adapter.stop()
# Proposal, same as other agents but timing is focused in for gradual.
async def proposal_generator():
    "Background task to generate strategic proposals"
    negotiation_counter = 0
    
    await asyncio.sleep(10)  # Strategic delay - let others go first
    logger.info("Strategic proposal generator starting")
    
    try:
        while True:
            await asyncio.sleep(random.uniform(15, 25))  # VERY patient timing.
            
            negotiation_counter += 1
            
            try:
                import uuid
                ID = str(uuid.uuid4())
                
                # LLM proposal generation
                try:
                    context = {
                        "negotiation_count": negotiation_counter,
                        "strategy": "gradual_patience",
                        "resource_type": "computing_cycles",
                        "quantity": 0,
                        "offer_value": 0,
                        "round": negotiation_counter
                    }
                    
                    llm_prompt = get_negotiation_prompt("gradual", "generate_proposal", context)
                    logger.info("Gradual agent generating strategic proposal...")
                    
                    llm_response = await call_llm(llm_prompt)
                    # PARSE
                    if llm_response:
                        try:
                            proposal = json.loads(llm_response)
                            resource_type = proposal.get("resource_type", "computing_cycles")
                            quantity = proposal.get("quantity", random.randint(10, 25))
                            offer_value = proposal.get("offer_value", random.randint(150, 250))
                            
                            msg = make_msg(propose, 
                                ID=ID,
                                resource_type=resource_type,
                                quantity=quantity,
                                offer_value=offer_value
                            )
                            
                            logger.info(f"Sending LLM strategic proposal {negotiation_counter}: {quantity} {resource_type} for {offer_value}")
                            await adapter.send(msg)
                            continue
                        except:
                            logger.info("Failed to parse LLM proposal, using fallback")
                except Exception as e:
                    logger.info(f"LLM proposal generation failed: {e}, using fallback")
                
                # Fallback to hard coded if LLM failure.
                resource_type = "computing_cycles"
                quantity = random.randint(10, 25)  # Strategic - smaller quantities
                offer_value = random.randint(150, 250)  # Strategic - higher value offers
                # making proposal
                msg = make_msg(propose, 
                    ID=ID,
                    resource_type=resource_type,
                    quantity=quantity,
                    offer_value=offer_value
                )
                
                logger.info(f"Sending strategic proposal {negotiation_counter}: {quantity} {resource_type} for {offer_value}")
                
                await adapter.send(msg)
                logger.info(f"Sent strategic proposal {negotiation_counter}")
                stats.total_negotiations += 1
                
            except Exception as e:
                logger.error(f"Failed to send proposal: {e}")
                
    except asyncio.CancelledError:
        logger.info(f"Strategic agent stopped. Final agreements: {stats.successful_agreements}")
        raise
# main
async def main():
    "Main execution - runs continuously, can both send and receive"
    logger.info("Gradual Agent starting")
    logger.info("Agent can both send and receive proposals...")
    
    # Start proposal generation
    asyncio.create_task(proposal_generator())
    
    await asyncio.sleep(0.1)
# entry point
if __name__ == "__main__":
    try:
        logger.info("Starting Gradual Agent (AgentC)...")
        adapter.start(main())
    except KeyboardInterrupt:
        logger.info("Agent stopped")
    except Exception as e:
        logger.error(f"Agent error: {e}")