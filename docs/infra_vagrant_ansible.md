What Vagrant Does Overall? 

  Creates the Computers. 
  
  Answers: 
  - What computers exist, and how are they connected?
  - How many machines exist?
  - Are they Windows or Linux?
  - How much RAM/CPU do they get?
  - Are they on the same network?
  - Can they talk to each other?

How we can use Vargrant in our project? 

  Creates:
  - Windows Server (Domain Controller) //Main computer that controls the whole company network
  - Windows Workstations //Regular "employee" computers 
  - Linux Attacker // Fake "hacker" computer 
  - SIEM (Security Information and Event Management) machine //Security monitoring computer 
  
  Sets up networking so:
  - Workstations talk to the DC //Employee computers can log in > Password check by Domain Controller 
  - Attacker can reach the network
  
  - Lets you destroy everything and start fresh after an attack.
  - Call Ansible automatically

Vagrant Commands:
  vagrant destroy -f //Lets you destroy everything and start fresh after an attack. 
  vagrant up //Rebuild them exactly as before


What Ansible does? 

  Set up what’s inside the computers.
  
  Answers: 
  - How do we turn this Windows Server into a Domain Controller?
  - How do we join machines to the domain?
  - How do we install Wazuh, Sysmon, Ghosts agents?
  - How do we configure logging?
  - How do we intentionally make weak settings for attacks?
  - How can we use Ansible for our project?

How we can use Ansible in our project? 
  Ansible will:
  
  - Turn a Windows Server into a Domain Controller // Make the boss of the network
  - Create domain users //Create fake employees like "Alice" and "Bob"
  - Join machines to the domain 
    Install:
    - Wazuh agent //Security watcher 
    - Sysmon //Actvity tracker 
    - Ghosts agent //Pertend real human user
  - Configure logging and weak configs
  - Prepare machines for attacks





