# Configuration for the system.

import bspl

negotiation = bspl.load_file("negotiation.bspl").export("Negotiation")
from Negotiation import AgentA, AgentB

# Network addresses to ensure all agents can communicate.
agents = {
    "AgentA": [("127.0.0.1", 8010)],  # Aggressive Agent
    "AgentB": [("127.0.0.1", 8011)],  # Cooperative Agent  
    "AgentC": [("127.0.0.1", 8012)],  # Gradual Agent
}

# Ensuring each agent can propose and respond.
systems = {
    "negotiation": {
        "protocol": negotiation,
        "roles": {
            AgentA: "AgentA", 
            AgentB: "AgentB",
            # Note: AgentC will dynamically map to AgentA or AgentB role as needed
        },
    },
}

# Resources to be exchanged. Pretty much arbitrary. No context in this system needed. Just want simple numbered deals to capture negotiation dynamics.
RESOURCE_TYPES = [
    "computing_cycles",
    "data_storage", 
    "network_bandwidth",
    "processing_time",
    "memory_allocation",
    "security_tokens",
    "access_rights",
    "priority_slots"
]

# How each agent should behave.
AGENT_CONFIGS = {
    "Aggressive": {
        "personality": "aggressive",
        "initial_needs": {"computing_cycles": 100, "data_storage": 80, "network_bandwidth": 60},
        "satisfaction_threshold": 0.6,  # Lower threshold, easier to satisfy
        "concession_rate": 0.3,  # High concession rate for quick deals
        "offer_aggressiveness": 0.8,  # Start with aggressive offers
        "deadline_pressure": 0.9,  # High pressure to close deals
    },
    "Cooperative": {
        "personality": "cooperative", 
        "initial_needs": {"processing_time": 90, "memory_allocation": 70, "security_tokens": 50},
        "satisfaction_threshold": 0.7,  # Moderate threshold
        "concession_rate": 0.5,  # Balanced concession rate
        "offer_aggressiveness": 0.4,  # Fair initial offers
        "deadline_pressure": 0.5,  # Moderate deadline pressure
    },
    "Gradual": {
        "personality": "gradual",
        "initial_needs": {"access_rights": 85, "priority_slots": 95, "computing_cycles": 75},
        "satisfaction_threshold": 0.85,  # High threshold, harder to satisfy
        "concession_rate": 0.15,  # Low concession rate, stubborn
        "offer_aggressiveness": 0.2,  # Conservative initial offers
        "deadline_pressure": 0.3,  # Low deadline pressure
    }
}

# Scoring weights for negotiation eval.
SCORING_WEIGHTS = {
    "individual_utility": 0.3,
    "opponent_utility": 0.2,
    "nash_product": 0.25,
    "social_welfare": 0.15,
    "agreement_ratio": 0.1
}