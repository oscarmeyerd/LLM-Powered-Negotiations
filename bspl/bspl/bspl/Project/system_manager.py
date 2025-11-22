#!/usr/bin/env python3
# CLI interface for managing the automated negotiations.

import os
import subprocess
import time
from pathlib import Path

# Class to manage negotiation system interactions
class SystemManager:
    def __init__(self):
        self.project_dir = Path(__file__).parent
        self.venv_python = self.project_dir.parent / "venv" / "Scripts" / "python.exe"
        # Agent definitions
        self.agents = {
            "A": {
                "name": "Aggressive Agent",
                "file": "aggressive_agent.py",
                "description": "Prioritizes deal completion over utility maximization",
                "strategy": "Quick decisions, high concession rates",
                "port": 8010,
                "adapter_name": "AgentA"
            },
            "C": {
                "name": "Cooperative Agent", 
                "file": "cooperative_agent.py",
                "description": "Seeks mutually beneficial outcomes",
                "strategy": "Balances own needs with opponent satisfaction",
                "port": 8011,
                "adapter_name": "AgentB"
            },
            "G": {
                "name": "Gradual Agent",
                "file": "gradual_agent.py", 
                "description": "Prioritizes individual utility maximization",
                "strategy": "Strategic, patient, willing to walk away",
                "port": 8012,
                "adapter_name": "AgentC"
            }
        }
        # System modes
        self.system_modes = {
            "1": ("Bilateral Negotiation", "Two agents negotiate against each other"),
            "2": ("Round Robin", "All agents compete in multiple pairings"),
            "3": ("Human vs Agent", "Practice negotiating with AI agents")
        }
    # Display header information
    def display_header(self):
        print("=" * 80)
        print("AUTOMATED NEGOTIATION SYSTEM MANAGER")
        print("=" * 80)
        print("Research System for Automated Negotiating Agent Competition")
        print()
    # Display available agents
    def display_agents(self):
        print("Available Agents:")
        print("-" * 50)
        for key, agent in self.agents.items():
            print(f"  [{key}] {agent['name']}")
            print(f"      Strategy: {agent['strategy']}")
            print(f"      Port: {agent['port']} | File: {agent['file']}")
            print()
    # Display system modes
    def display_system_modes(self):
        print("System Modes:")
        print("-" * 30)
        for key, (name, desc) in self.system_modes.items():
            print(f"  [{key}] {name}")
            print(f"      {desc}")
            print()
    # Process user choice input for menu selections
    def get_user_choice(self, prompt, valid_choices):
        while True:
            choice = input(f"{prompt} [{'/'.join(valid_choices)}]: ").upper().strip()
            if choice in valid_choices:
                return choice
            print(f"ERROR: Invalid choice. Please select from: {', '.join(valid_choices)}")
    # Startup human vs agent negotiation interface
    def launch_human_negotiation(self):
        "Launch human vs agent negotiation interface"
        print(f"\nLaunching Human-Agent Negotiation Interface...")
        print("This will open an interactive negotiation session where you can")
        print("practice your negotiation skills against any of the AI agents.")
        print("\nFeatures:")
        print("  • Guided input validation and coaching")
        print("  • Real-time strategy tips for each agent type")  
        print("  • Complete negotiation tutorial")
        print("  • Session analysis and feedback")
        # Exit anytime with Ctrl+C\n")
        try:
            cmd = [str(self.venv_python), "human_negotiator.py"]
            process = subprocess.Popen(
                cmd,
                cwd=self.project_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
            )
            
            print(f"\nSUCCESS: Human-Agent Negotiator launched (PID: {process.pid})")
            print("Check the new terminal window to start negotiating!")
            
        except Exception as e:
            print(f"ERROR: Failed to launch human negotiator: {e}")
    # Agent selection from user. Who do they want to fight.
    def get_agent_selection(self, prompt="Select agents", min_agents=2, max_agents=3):
        while True:
            print(f"\n{prompt}")
            self.display_agents()
            
            selection = input("Enter agent codes (e.g., 'A', 'AC', 'ACG'): ").upper().strip()
            
            # Validate selection
            selected_agents = []
            valid = True
            
            for char in selection:
                if char in self.agents:
                    if char not in selected_agents:
                        selected_agents.append(char)
                    else:
                        print(f"ERROR: Agent {char} selected multiple times")
                        valid = False
                        break
                else:
                    print(f"ERROR: Invalid agent code: {char}")
                    valid = False
                    break
            
            if valid and min_agents <= len(selected_agents) <= max_agents:
                return selected_agents
            elif not valid:
                continue
            else:
                print(f"ERROR: Please select between {min_agents} and {max_agents} agents")
        # Starting the bilateral (two-agent) negotiation.
    def launch_bilateral_negotiation(self, agent_codes):
        "Launch bilateral negotiation between two agents"
        if len(agent_codes) != 2:
            print("ERROR: Bilateral negotiation requires exactly 2 agents")
            return
            
        agent1, agent2 = agent_codes
        
        print(f"\nLaunching Bilateral Negotiation:")
        print(f"  Agent 1: {self.agents[agent1]['name']} ({agent1})")
        print(f"  Agent 2: {self.agents[agent2]['name']} ({agent2})")
        print("\nUsing static configuration...")
        
        # Agent port mappings (from configuration.py). This ensures agents connect properly.
        port_mapping = {"A": 8010, "C": 8011, "G": 8012}
        print(f"  {agent1} -> Port: {port_mapping[agent1]}")
        print(f"  {agent2} -> Port: {port_mapping[agent2]}")
        
        print("\nBoth agents will be launched in separate windows")
        print("Press Ctrl+C in either window to stop the negotiation\n")
        
        try:
            processes = []
            
            for agent_code in agent_codes:
                agent = self.agents[agent_code]
                cmd = [str(self.venv_python), agent['file']]
                # Launch agent process
                process = subprocess.Popen(
                    cmd,
                    cwd=self.project_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
                )
                processes.append(process)
                
                print(f"SUCCESS: Launched {agent['name']} (PID: {process.pid})")
                time.sleep(1)  # Brief delay for startup
            
            print(f"\nSystem: Bilateral negotiation started successfully!")
            print("Check both terminal windows for negotiation progress")
            
        except Exception as e:
            print(f"ERROR: Failed to launch negotiation: {e}")
    # Starting round-robin negotiations. All agents negotiate with each other.
    def launch_round_robin(self, agent_codes):
        "Launch round-robin negotiations with sequential bilateral matches"
        if len(agent_codes) < 2:
            print("ERROR: Round-robin negotiations require at least 2 agents")
            return
            
        print(f"\nLaunching Round-Robin Negotiations:")
        for agent_code in agent_codes:
            print(f"  - {self.agents[agent_code]['name']} ({agent_code})")
        
        # Create all possible matches for round-robin (AG, AC, CG)
        matches = []
        for i in range(len(agent_codes)):
            for j in range(i + 1, len(agent_codes)):
                matches.append((agent_codes[i], agent_codes[j]))
        
        print(f"\nThis will create {len(matches)} bilateral matches:")
        for i, (agent1, agent2) in enumerate(matches, 1):
            print(f"  Match {i}: {self.agents[agent1]['name']} vs {self.agents[agent2]['name']}")
        
        print(f"\nEach match will run for 60 seconds, then move to the next pair")
        
        confirm = input("\nProceed with round-robin negotiations? [y/N]: ").lower().strip()
        if confirm != 'y':
            print("Negotiations cancelled")
            return
        # Starting matches
        try:
            print(f"\nStarting Round-Robin Negotiations with {len(matches)} matches...")
            
            for match_num, (agent1, agent2) in enumerate(matches, 1):
                print(f"\n{'='*60}")
                print(f"MATCH {match_num}/{len(matches)}: {self.agents[agent1]['name']} vs {self.agents[agent2]['name']}")
                print("="*60)
                
                # Launch bilateral match
                processes = []
                
                for agent_code in [agent1, agent2]:
                    agent = self.agents[agent_code]
                    cmd = [str(self.venv_python), agent['file']]
                    
                    process = subprocess.Popen(
                        cmd,
                        cwd=self.project_dir,
                        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
                    )
                    processes.append(process)
                    
                    print(f"Launched {agent['name']} (PID: {process.pid})")
                    time.sleep(1)
                
                print(f"\nMatch {match_num} running for 60 seconds...")
                print("Watch the agent windows for negotiation activity")
                
                # Let match run for 60 seconds
                time.sleep(60)
                
                # Terminate processes
                print(f"\nStopping Match {match_num}...")
                for process in processes:
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                        print(f"Stopped process {process.pid}")
                    except Exception as e:
                        print(f"Warning: Could not stop process {process.pid}: {e}")
                
                if match_num < len(matches):
                    print("Preparing next match...")
                    time.sleep(3)  # Brief pause between matches
            # Final summary
            print(f"\n{'='*60}")
            print("ROUND-ROBIN NEGOTIATIONS COMPLETED!")
            print(f"All {len(matches)} matches have finished.")
            print("="*60)
        # Failure handling  
        except Exception as e:
            print(f"ERROR: Failed to run negotiations: {e}")
        except KeyboardInterrupt:
            print(f"\nNegotiations interrupted by user!")
            print("Stopping any running processes...")
            # Cleanup will be handled by the calling code
    # Checking if all prerequisites are met to ensure smooth operation
    def check_prerequisites(self):
        "Check if all required files and environment are ready"
        print("Checking system prerequisites...")
        
        issues = []
        
        # Check if in correct directory
        if not (self.project_dir / "aggressive_agent.py").exists():
            issues.append("aggressive_agent.py not found")
        if not (self.project_dir / "cooperative_agent.py").exists():
            issues.append("cooperative_agent.py not found") 
        if not (self.project_dir / "gradual_agent.py").exists():
            issues.append("gradual_agent.py not found")
        
        # Check virtual environment. Venv needed for dependencies.
        if not self.venv_python.exists():
            issues.append(f"Python virtual environment not found at {self.venv_python}")
        
        # Check .env file
        if not (self.project_dir / ".env").exists():
            issues.append(".env file not found (API keys required)")
        #Error handling to report issues to user.
        if issues:
            print("ERROR: Prerequisites check failed:")
            for issue in issues:
                print(f"   - {issue}")
            print("\nPlease fix these issues before running negotiations")
            return False
        else:
            print("SUCCESS: All prerequisites satisfied")
            return True
    # Main CLI
    def run(self):
        "Main CLI interface"
        self.display_header()
        
        if not self.check_prerequisites():
            input("\nPress Enter to exit...")
            return
        
        while True:
            print("\n" + "="*50)
            self.display_system_modes()
            
            mode = self.get_user_choice("Select system mode", list(self.system_modes.keys()) + ['Q'])
            
            if mode == 'Q':
                print("\nThank you for using the Negotiation System Manager!")
                break
            
            try:
                if mode == "1":  # Bilateral Negotiation
                    agents = self.get_agent_selection("Select two agents for bilateral negotiation", min_agents=2, max_agents=2) 
                    self.launch_bilateral_negotiation(agents)
                    
                    # Logging to ensure user knows the agents are running
                    print(f"\nAgents are running continuously in separate windows")
                    print(f"Monitor their negotiation progress in the terminal windows")
                    print(f"Press Ctrl+C in either agent window to stop the negotiation")
                    input(f"\nPress ENTER when you're ready to return to the main menu...")
                    
                elif mode == "2":  # Round Robin
                    agents = self.get_agent_selection("Select agents for round-robin negotiations", min_agents=2, max_agents=3)
                    self.launch_round_robin(agents)
                    print(f"\nNegotiations completed")
                    
                elif mode == "3":  # Human vs Agent
                    self.launch_human_negotiation()
                    print(f"\nNegotiation session completed")
                
                # Ask if user wants to run again
                another = input("\nRun another negotiation session? [y/N]: ").lower().strip()
                if another != 'y':
                    break
                    
            except KeyboardInterrupt:
                print("\n\nNegotiation setup cancelled")
                continue
            except Exception as e:
                print(f"\nERROR: {e}")
                continue

# Entry point
def main():
    "Entry point for the CLI system manager"
    try:
        manager = SystemManager()
        manager.run()
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
    except Exception as e:
        print(f"\nERROR: Fatal error: {e}")
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
