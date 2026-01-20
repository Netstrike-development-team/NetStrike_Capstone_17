# NetStrike_Capstone_17
Class: SEG 4910 

Team members: Ashley Goman, Anna Brimacombe-Tanner, Patrick Luu, Aya Debbagh

Client: Dr. Miguel Gazon

Mission: This project aims to build a cloud-hosted platform that allows companies, researchers, and students to model an enterprise network, deploy it automatically in the cloud, and run realistic cyber-attack scenarios based on known threat actors. The goal is to give users a safe environment to study attacker behavior, analyze logs, observe IOCs, and understand how different security appliances respond during a full attack chain.

Description: Users will design their environment through an intuitive UI with a drag-and-drop network builder, where they can select workstations, servers, domain controllers, firewalls, SIEM tools, and other components. The system will deploy these elements as VMs in the cloud using automated provisioning. Once the environment is created, users can choose from curated attack scripts that replicate real adversary TTPs mapped to MITRE ATT&CK (e.g., TA505, APT29, FIN7). Running these simulations will show exactly how an attacker would progress through that network. A dedicated dashboard will let users monitor the attack in real time, view a visual timeline of attacker steps, explore network impact, and inspect logs from every appliance (SIEM alerts, firewall events, endpoint telemetry, server logs, etc.). The platform will also surface indicators of compromise and provide visualizations of lateral movement paths.
