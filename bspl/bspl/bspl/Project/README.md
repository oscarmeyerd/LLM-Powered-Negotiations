# Intro to the system.

This system is an automated negotiation system similar to what is seen in the annual ANAC competitions. The goal of this system is to get a better idea of how agents with different priorities can maximize their personal value gain while still completing transactions.
All exchanged resources are arbitrary just to provide the agents with decision-making parameters. 

The system contains three agents with differing "personalities" to emphasize what priorities make for a great automated negotiator. Those agents are aggressive (prioritize quick deals), cooperative (prioritize FAIR deals to both parties), and gradual (prioritize value gain of self).

The system allows for three possible transaction modes: Bilateral (agent-agent), round robin (agent-agent-agent), and human negotiation (human-agent). Setup instructions and further information about the transactions are below.

## Further agent explanation.

- **Aggressive** - Fast decisions, prioritizes deal completion
- **Cooperative** - Seeks fair, mutually beneficial outcomes
- **Gradual** - Strategic, patient, maximizes individual utility

## Further mode explanations.

- **Bilateral** - Two agent negotiation
- **Round-Robin** - All possible pairings
- **Human vs AI** - Interactive negotiation with immense coaching from the user interface.

## Resources explanations.

8 resource types: computing_cycles, data_storage, network_bandwidth, processing_time, memory_allocation, security_tokens, access_rights, priority_slots

## Expected agent decision-making guidelines.

- **Aggressive**: High agreement rate, moderate utility. Make as many deals as possible.
- **Cooperative**: High social welfare, balanced outcomes. Wants to continue making deals.
- **Gradual**: High individual utility, selective agreements. Gain as much as possible.

## Setup instructions.

1. **Activate virtual environment**
   .\activate.ps1 <- only powershell is capable at this moment
 
 **Note:** Running activate.ps1 will enter a virtual environment indicated by (venv) in front of your command line. Ensure this is the case before proceeding to the installation of dependencies.

2. **Install dependencies (if not already installed)**
   
   # Install build tools first
   pip install setuptools wheel
   
   # Install BSPL framework and all its dependencies
   pip install -e .
   
   # Install additional LLM integration dependencies
   pip install aiohttp python-dotenv
   

3. **Configure .env**

   OPENROUTER_API_KEY_AGGRESSIVE=your_key_here <- Place API keys generated from openrouter here.
   OPENROUTER_API_KEY_COOPERATIVE=your_key_here  
   OPENROUTER_API_KEY_GRADUAL=your_key_here
   OPENROUTER_MODEL=meta-llama/llama-3.2-3b-instruct:free
   

4. **Usage**

   .\start_system.ps1 <- Only windows usage is included at this time.

As a final note, all user inputs include interface messaging with further usage instructions. Therefore, they are not included here. To see these instructions, run the system using the human-agent mode.

