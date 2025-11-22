#!/usr/bin/env python3

# Interface for a human to negotiate against any of the three agents. Includes easy to use logging to assist in negotiation. Input validation to ensure no errors. The human user is interacting directly with the LLM powered agents.

import asyncio
import json
import random
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Tuple
from llm import call_llm, get_negotiation_prompt
from metrics import NegotiationStats


class HumanNegotiator:
    "Simplified human-agent negotiation interface"
    
    def __init__(self):
        self.project_dir = Path(__file__).parent
        self.venv_python = self.project_dir.parent / "venv" / "Scripts" / "python.exe"
        
        # Agent definitions
        self.agents = {
            "A": {"name": "Aggressive Agent", "file": "aggressive_agent.py", "port": 8010,
                  "strategy": "Quick deals, high concession rates", "personality": "impatient"},
            "C": {"name": "Cooperative Agent", "file": "cooperative_agent.py", "port": 8011,
                  "strategy": "Seeks win-win outcomes", "personality": "collaborative"},
            "G": {"name": "Gradual Agent", "file": "gradual_agent.py", "port": 8012,
                  "strategy": "Patient, utility-focused", "personality": "strategic"}
        }
        
        # Simplified resource configuration with limits
        self.resources = ["computing_cycles", "data_storage", "network_bandwidth", "processing_time"]
        self.resource_ranges = {
            "computing_cycles": (1, 100),
            "data_storage": (1, 500),
            "network_bandwidth": (1, 100),
            "processing_time": (1, 50)
        }
        # Metrics for the current negotiation session (per-agent)
        self.stats = NegotiationStats()
    # Fun logging for human readdability
    def display_header(self):
        "Display welcome header"
        print("=" * 60)
        print("HUMAN-AGENT NEGOTIATION INTERFACE")
        print("=" * 60)
        print("Practice your negotiation skills with AI agents!\n")
    # Agent selection. Which do you want to negotiate with?
    def get_agent_choice(self) -> str:
        "Get user's agent selection"
        print("Available Agents:")
        for code, agent in self.agents.items():
            print(f"  [{code}] {agent['name']}: {agent['strategy']}")
        # Input validation loop
        while True:
            choice = input("\nSelect agent [A/C/G] or Q to quit: ").upper().strip()
            if choice == 'Q':
                return None
            if choice in self.agents:
                return choice
            print("Invalid choice. Please select A, C, G, or Q.")
    # Offer creation - again, input is validated.
    def create_offer(self) -> Dict[str, int]:
        "Create a resource offer with simplified input"
        print("\nCreate your offer:")
        offer = {}
        
        for resource in self.resources:
            min_val, max_val = self.resource_ranges[resource]
            while True:
                try:
                    prompt = f"{resource.replace('_', ' ').title()} ({min_val}-{max_val}): "
                    value = int(input(prompt))
                    if min_val <= value <= max_val:
                        offer[resource] = value
                        break
                    else:
                        print(f"Value must be between {min_val} and {max_val}")
                except ValueError:
                    print("Please enter a valid number")
        
        return offer
    # Displaying offer.
    def display_offer(self, offer: Dict[str, int], label: str = "Offer"):
        "Display an offer in a clean format"
        print(f"\n{label}:")
        for resource, value in offer.items():
            print(f"  {resource.replace('_', ' ').title()}: {value}")
    # Getting action from user. Three options.
    def get_action(self) -> str:
        "Get negotiation action from user"
        print("\nWhat would you like to do?")
        print("  [P] Propose new offer")
        print("  [A] Accept current offer") 
        print("  [R] Reject and end negotiation")
        # Validation
        while True:
            action = input("Choose action [P/A/R]: ").upper().strip()
            if action in ['P', 'A', 'R']:
                return action
            print("Invalid choice. Please select P, A, or R.")
    # Retrieving AI agent responses.
    async def get_agent_response(self, agent_code: str, human_offer: Dict[str, int], round_num: int) -> Tuple[str, Optional[Dict[str, int]]]:
        "Get real AI agent response using the same LLM system as the actual agents"
        agent = self.agents[agent_code]
        
        # Agent selection mapping to LLM roles.
        agent_type_map = {
            "A": "aggressive",
            "C": "cooperative", 
            "G": "gradual"
        }
        # Agent TYPE
        agent_type = agent_type_map[agent_code]
        
        # Calculate total offer value for LLM context
        total_value = sum(human_offer.values())
        
        # Prepare context for LLM
        context = {
            "resource_type": "mixed_resources",
            "quantity": len(human_offer),
            "offer_value": total_value,
            "round": round_num,
            "human_offer": human_offer
        }
        
        try:
            # Get LLM decision
            print(f"{agent['name']} is thinking...")
            prompt = get_negotiation_prompt(agent_type, "evaluate_proposal", context)
            llm_response = await call_llm(prompt, role=agent_type)
            
            if llm_response:
                try:
                    decision = json.loads(llm_response)
                    
                    if decision.get("decision") == "ACCEPT":
                        print(f"{agent['name']} decides to accept")
                        return "accept", None
                    elif decision.get("decision") == "COUNTER" or decision.get("decision") not in ["ACCEPT", "REJECT"]:
                        # Generate counter-offer using LLM
                        print(f"{agent['name']} is preparing a counter-offer...")
                    elif decision.get("decision") == "REJECT":
                        print(f"{agent['name']} decides to reject")
                        return "reject", None
                    else:
                        # Fallback - generate counter-offer
                        print(f"{agent['name']} is preparing a counter-offer...")
                        counter_context = {
                            "resource_type": "mixed_resources",
                            "quantity": len(human_offer),
                            "offer_value": total_value,
                            "round": round_num,
                            "previous_offer": human_offer
                        }
                        # Counter-offer generation
                        counter_prompt = get_negotiation_prompt(agent_type, "generate_proposal", counter_context)
                        counter_response = await call_llm(counter_prompt, role=agent_type)
                        # Processing counter-offer
                        if counter_response:
                            try:
                                proposal = json.loads(counter_response)
                                counter_offer = self.generate_intelligent_counter(human_offer, proposal, agent_type)
                                print(f"{agent['name']} made an AI-driven counter-offer")
                                return "counter", counter_offer
                            except:
                                print(f"{agent['name']} falls back to intelligent counter")
                                fallback_proposal = {'offer_value': 100}
                                return "counter", self.generate_intelligent_counter(human_offer, fallback_proposal, agent_type)
                        
                except json.JSONDecodeError:
                    print(f"{agent['name']} had trouble parsing AI decision, using fallback")
                    
        except Exception as e:
            print(f"{agent['name']} AI error: {e}, using fallback logic")
        
        # Fallback to hardcoded if LLM fails
        if agent["personality"] == "impatient":  # Aggressive
            if round_num <= 2:
                fallback_proposal = {'offer_value': 80}
                return "counter", self.generate_intelligent_counter(human_offer, fallback_proposal, "aggressive")
            else:
                return "accept", None
                
        elif agent["personality"] == "collaborative":  # Cooperative
            if round_num <= 3:
                fallback_proposal = {'offer_value': 100}
                return "counter", self.generate_intelligent_counter(human_offer, fallback_proposal, "cooperative")
            else:
                return "accept", None
                
        else:  # Gradual - strategic
            if round_num <= 4 and random.random() < 0.7:
                fallback_proposal = {'offer_value': 120}
                return "counter", self.generate_intelligent_counter(human_offer, fallback_proposal, "gradual")
            elif round_num <= 6:
                return "accept", None
            else:
                return "reject", None
    # Counter-offer generation logic.
    def generate_counter_offer(self, human_offer: Dict[str, int], factor: float) -> Dict[str, int]:
        "Generate a counter-offer based on human offer"
        counter = {}
        for resource, value in human_offer.items():
            min_val, max_val = self.resource_ranges[resource]
            # Adjust offer by factor with some randomness
            new_value = int(value * factor * random.uniform(0.9, 1.1))
            counter[resource] = max(min_val, min(max_val, new_value))
        return counter
    # Counter-offer logic
    def generate_intelligent_counter(self, human_offer: Dict[str, int], llm_proposal: Dict, agent_type: str) -> Dict[str, int]:
        "Generate counter-offer using LLM guidance and resource constraints"
        counter = {}
        
        # Extracting suggestions from LLM
        suggested_value = llm_proposal.get("offer_value", 100)  # Default to reasonable value
        suggested_quantity = llm_proposal.get("quantity", 20)
        
        # If human offer is too low, make a meaningful counter-offer
        total_current = sum(human_offer.values())
        
        # Set minimum acceptable counter-offer values based on agent type
        if agent_type == "aggressive":
            min_counter_total = 60  # Aggressive but not unreasonable
        elif agent_type == "cooperative":
            min_counter_total = 80  # Fair value
        else:  # gradual
            min_counter_total = 100  # High standards
        
        # Use LLM suggestion or minimum, whichever is higher
        target_total = max(suggested_value, min_counter_total)
        
        # If human offer was very low, make a reasonable counter
        if total_current < 20:
            target_total = max(target_total, min_counter_total)
        
        # distribute target total across resources
        for resource, value in human_offer.items():
            min_val, max_val = self.resource_ranges[resource]
            
            # Base the counter on the resource type
            if resource == "computing_cycles":
                counter_val = max(10, int(target_total * 0.3))
            elif resource == "data_storage":
                counter_val = max(50, int(target_total * 0.4))
            elif resource == "network_bandwidth":
                counter_val = max(15, int(target_total * 0.2))
            else:  # processing time
                counter_val = max(5, int(target_total * 0.1))
            
            # Ensure it's in range
            counter[resource] = min(counter_val, max_val)
        
        return counter
    # Running negotiation
    async def run_negotiation(self, agent_code: str):
        "Run a complete AI-powered negotiation session"
        # Fun logging for human readability
        agent = self.agents[agent_code]
        print(f"\n{'='*50}")
        print(f"NEGOTIATING WITH {agent['name'].upper()}")
        print(f"Strategy: {agent['strategy']}")
        print(f"{'='*50}")
        
        round_num = 1 # round counter
        current_offer = None
        session_history = []
        
        while round_num <= 3:  # demo 3 rounds b/c time.
            print(f"\n--- Round {round_num} ---")
            
            # prompt for human input
            action = self.get_action()
            
            if action == 'P':  # Propose
                human_offer = self.create_offer()
                self.display_offer(human_offer, "Your Offer")
                current_offer = human_offer
                # record that human made an offer
                self.stats.total_offers_made += 1
                
                # Get agent response
                agent_response, agent_offer = await self.get_agent_response(agent_code, human_offer, round_num)
                
                if agent_response == "accept":
                    print(f"\nSUCCESS! {agent['name']} accepted your offer!")
                    self.display_offer(human_offer, "Final Agreement")
                    # Record metrics for agreement (normalized)
                    self.stats.successful_agreements += 1
                    self.stats.total_negotiations += 1
                    agreement = human_offer
                    self._record_agreement(agreement)
                    session_history.append({"round": round_num, "human_offer": human_offer, "agent_offer": None, "outcome": "accept"})
                    self.stats.negotiation_history.extend(session_history)
                    self.print_metrics(agent_code)
                    return
                elif agent_response == "reject":
                    print(f"\n{agent['name']} rejected your offer and ended negotiations.")
                    # Record metrics (no agreement)
                    self.stats.total_negotiations += 1
                    session_history.append({"round": round_num, "human_offer": human_offer, "agent_offer": None, "outcome": "reject"})
                    self.stats.negotiation_history.extend(session_history)
                    self.print_metrics(agent_code)
                    return
                else:  # counter
                    print(f"\n{agent['name']} made a counter-offer:")
                    self.display_offer(agent_offer, f"{agent['name']}'s Counter-Offer")
                    current_offer = agent_offer
                    # record that agent made a counter
                    self.stats.total_offers_received += 1
                    session_history.append({"round": round_num, "human_offer": human_offer, "agent_offer": agent_offer, "outcome": "counter"})
                    
            elif action == 'A':  # Accept
                if current_offer:
                    print(f"\nYou accepted {agent['name']}'s offer!")
                    self.display_offer(current_offer, "Final Agreement")
                    # Record metrics for agreement (normalized)
                    self.stats.total_offers_received += 1
                    self.stats.successful_agreements += 1
                    self.stats.total_negotiations += 1
                    agreement = current_offer
                    self._record_agreement(agreement)
                    session_history.append({"round": round_num, "human_offer": None, "agent_offer": current_offer, "outcome": "accept"})
                    self.stats.negotiation_history.extend(session_history)
                    self.print_metrics(agent_code)
                    return
                else:
                    print("No offer to accept yet!")
                    continue
                    
            else:  # Reject
                print(f"\nNegotiation ended. No agreement reached with {agent['name']}.")
                # Record metrics (human ended negotiation)
                self.stats.total_negotiations += 1
                session_history.append({"round": round_num, "human_offer": None, "agent_offer": current_offer, "outcome": "human_reject"})
                self.stats.negotiation_history.extend(session_history)
                self.print_metrics(agent_code)
                return
            
            round_num += 1 # increment round
        
        print(f"\nNegotiation reached the 3-round limit. No agreement reached.")
        # Reached limit: metric processing
        self.stats.total_negotiations += 1
        self.stats.negotiation_history.extend(session_history)
        self.print_metrics(agent_code)

    def print_metrics(self, agent_code: str):
        """Print a concise summary of negotiation metrics for the agent."""
        agent = self.agents.get(agent_code, {"name": agent_code})
        print("\n" + "=" * 40)
        print(f"Performance metrics for {agent['name']}")
        print("=" * 40)
        print(f"  Total negotiations (this session): {self.stats.total_negotiations}")
        print(f"  Successful agreements: {self.stats.successful_agreements}")
        print(f"  Offers made by human: {self.stats.total_offers_made}")
        print(f"  Offers received from agent: {self.stats.total_offers_received}")
        print(f"  Agreement ratio: {self.stats.agreement_ratio:.2f}")
        print(f"  Average individual utility: {self.stats.average_individual_utility:.2f}")
        print(f"  Average opponent utility: {self.stats.average_opponent_utility:.2f}")
        print(f"  Average Nash product: {self.stats.average_nash_product:.2f}")
        print(f"  Average social welfare: {self.stats.average_social_welfare:.2f}")
        print("\n  Recent negotiation history:")
        for h in self.stats.negotiation_history[-5:]:
            print(f"    Round {h.get('round')}: outcome={h.get('outcome')}, human_offer={'set' if h.get('human_offer') else 'none'}, agent_offer={'set' if h.get('agent_offer') else 'none'}")
        print("=" * 40 + "\n")

    def _record_agreement(self, agreement: Dict[str, int]):
        """Record normalized utilities for an agreement (human perspective = agreement values).

        Normalization: utility is scaled by the sum of per-resource maximums so values are in [0,1].
        The agent utility is taken as the complement (1 - human_utility) to keep social welfare bounded.
        """
        # compute maximum possible total across resources
        max_total = 0
        for rng in self.resource_ranges.values():
            # rng is (min, max)
            max_total += rng[1]

        # avoid division by zero
        if max_total <= 0:
            return 0.0, 0.0

        h_total = sum(agreement.values()) if agreement else 0
        # normalize
        h_util_norm = float(h_total) / float(max_total)
        # clamp to [0,1]
        h_util_norm = max(0.0, min(1.0, h_util_norm))
        a_util_norm = max(0.0, 1.0 - h_util_norm)

        # update stats (use normalized values)
        self.stats.individual_utility_sum += h_util_norm
        self.stats.opponent_utility_sum += a_util_norm
        self.stats.nash_product_sum += h_util_norm * a_util_norm
        self.stats.social_welfare_sum += (h_util_norm + a_util_norm)

        return h_util_norm, a_util_norm

    # Main loop
    async def run(self):
        "Main execution loop with AI-powered agents"
        self.display_header()
        print("Powered by AI - You're negotiating with real LLM-driven agents!\n")
        
        while True:
            agent_code = self.get_agent_choice()
            if agent_code is None:
                break
                
            await self.run_negotiation(agent_code)
            
            # Ask for another round
            another = input("\nNegotiate with another agent? [Y/n]: ").lower().strip()
            if another == 'n':
                break
        
        print("\nThanks for practicing your negotiation skills with AI agents!")

# main entry point
async def main():
    "Entry point for AI-powered negotiation"
    try:
        negotiator = HumanNegotiator()
        await negotiator.run()
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        print(f"Error: {e}")

# main entry point
if __name__ == "__main__":
    asyncio.run(main())