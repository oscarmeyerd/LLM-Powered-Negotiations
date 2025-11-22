# Performance metrics for evaluation of negotiations

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class NegotiationStats:
    "Tracks negotiation performance metrics for evaluation."
    total_negotiations: int = 0
    successful_agreements: int = 0
    total_offers_made: int = 0
    total_offers_received: int = 0
    individual_utility_sum: float = 0.0
    opponent_utility_sum: float = 0.0
    nash_product_sum: float = 0.0
    social_welfare_sum: float = 0.0
    negotiation_history: List[Dict] = field(default_factory=list)

    @property
    def agreement_ratio(self) -> float:
        return self.successful_agreements / max(self.total_negotiations, 1)
    
    @property
    def average_individual_utility(self) -> float:
        return self.individual_utility_sum / max(self.successful_agreements, 1)
    
    @property
    def average_opponent_utility(self) -> float:
        return self.opponent_utility_sum / max(self.successful_agreements, 1)
    
    @property
    def average_nash_product(self) -> float:
        return self.nash_product_sum / max(self.successful_agreements, 1)
    
    @property 
    def average_social_welfare(self) -> float:
        return self.social_welfare_sum / max(self.successful_agreements, 1)