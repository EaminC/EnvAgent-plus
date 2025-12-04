# Workflow Diagram Specification for EnvAgent-plus 2.0

This document provides detailed workflow descriptions for creating system diagrams. Use this specification to generate flowcharts, sequence diagrams, or architecture diagrams.

## 1. High-Level System Architecture

```
Components:
- User Interface: Command-line tool (provision_v2.py)
- AI Engine: OpenAI-compatible API
- OpenStack Integration: envboot/osutil.py (SDK wrapper)
- Chameleon Cloud: Hardware infrastructure

Connections:
- User -> CLI Tool
- CLI Tool -> AI Engine (4 decision points)
- CLI Tool -> OpenStack SDK (resource operations)
- OpenStack SDK -> Chameleon Cloud (API calls)
```

**Diagram Type**: Architecture Diagram
**Layout**: Layered (top to bottom)

### Layers:
1. **User Layer**: Command-line interface
2. **Application Layer**: provision_v2.py + modules
3. **Intelligence Layer**: AI client (requirement analysis, selection)
4. **Integration Layer**: envboot/osutil.py (OpenStack SDK)
5. **Infrastructure Layer**: Chameleon Cloud

### Data Flow:
- User Input (GitHub URL) → Application
- Application → AI (analysis requests)
- AI → Application (recommendations)
- Application → OpenStack SDK (API calls)
- OpenStack SDK → Chameleon (resource provisioning)
- Chameleon → OpenStack SDK (status updates)
- OpenStack SDK → Application (results)
- Application → User (progress + final info)

---

## 2. End-to-End Provisioning Workflow

### Main Flow (10 Steps)

**Step 0: Initialization**
- Input: User provides GitHub repository URL
- Actions:
  - Load configuration from .env file
  - Check OpenStack environment variables (OS_AUTH_URL, etc.)
  - Initialize AI client with API credentials
  - Create OpenStack SDK connection
- Output: Ready to proceed
- Time: ~1 second

**Step 1: Repository Analysis**
- Input: GitHub repository URL
- Actions:
  - Clone repository to /tmp directory
  - Scan for environment files:
    * requirements.txt
    * pyproject.toml
    * setup.py
    * environment.yml
    * Dockerfile
    * README.md
  - Extract file contents (limit 10KB each)
  - Send to AI for analysis
  - AI returns structured JSON with requirements
- Output: Requirements object
  ```json
  {
    "cpu_cores": 4,
    "ram_gb": 16,
    "gpu_required": true,
    "gpu_memory_gb": 8,
    "disk_gb": 50,
    "os_type": "ubuntu",
    "os_version": "22.04",
    "cuda_required": true,
    "python_version": "3.9"
  }
  ```
- Time: ~10-30 seconds

**Step 2: Image Selection (Two-Stage Process)**

*Stage 2A: Candidate Selection*
- Input: Requirements + Full image list (~100 images)
- Actions:
  - Query OpenStack for all available images
  - Filter to CC-* images (Chameleon Cloud images)
  - Send list to AI with requirements
  - AI selects 3-5 candidate images
- Output: Candidate list
  ```
  ["CC-Ubuntu22.04-CUDA", "CC-Ubuntu22.04-CUDA-20240326", "CC-Ubuntu20.04-CUDA"]
  ```
- Time: ~5 seconds

*Stage 2B: Final Selection*
- Input: Candidate images
- Actions:
  - Query detailed information for each candidate
  - Get: size, min_disk, min_ram, created_at
  - Send details to AI with requirements
  - AI selects best match
- Output: Final image name and ID
  ```
  {
    "name": "CC-Ubuntu22.04-CUDA",
    "id": "1052ba60-cbe6-45ad-91ac-6ad0807c6e23"
  }
  ```
- Time: ~5 seconds

**Step 3: SSH Key Management**
- Input: Key name from config or command-line
- Actions:
  - Check if keypair exists in OpenStack
  - If exists: Use existing
  - If not exists:
    * Option A: Create new keypair (save private key locally)
    * Option B: Import from existing public key file
  - Set permissions: chmod 600 on private key
- Output: Keypair name
- Time: ~1 second

**Step 4: Network Configuration**
- Input: Network name (default: "sharednet1")
- Actions:
  - Query OpenStack for network by name
  - Verify network exists and is accessible
  - Extract network UUID
- Output: Network ID (UUID)
- Time: ~1 second

**Step 5: Hardware Reservation (Lease Creation)**

*Stage 5A: Duration Determination*
- Input: Requirements + Current time
- Actions:
  - Send requirements to AI
  - AI analyzes project complexity
  - AI recommends duration (default: 24 hours)
- Output: Duration in hours + reasoning
- Time: ~5 seconds

*Stage 5B: Lease Creation*
- Input: Duration + Node type + Time window
- Actions:
  - Calculate start time (now + 2 minutes)
  - Calculate end time (start + duration)
  - Create Blazar lease with parameters:
    * resource_type: "physical:host"
    * min/max: 1
    * resource_properties: node type filter
  - Submit to Blazar API
- Output: Lease ID
- Time: ~2 seconds

*Stage 5C: Wait for Activation*
- Input: Lease ID
- Actions:
  - Poll lease status every 10 seconds
  - Check status: PENDING → ACTIVE
  - If ERROR: Raise exception
  - Timeout: 5 minutes
- Output: Reservation ID (from lease.reservations[0].id)
- Time: ~1-5 minutes (typical: 2 minutes)

**Step 6: Server Launch**

*Stage 6A: Server Creation*
- Input: All collected parameters
- Actions:
  - Call OpenStack compute API
  - Parameters:
    * name: server_name
    * image_id: from Step 2
    * flavor_id: "baremetal"
    * networks: [network_id from Step 4]
    * key_name: from Step 3
    * scheduler_hints: {"reservation": reservation_id from Step 5}
  - Submit server creation request
- Output: Server ID + initial status (BUILD)
- Time: ~2 seconds

*Stage 6B: Wait for Active*
- Input: Server ID
- Actions:
  - Poll server status every 30 seconds
  - Check status: BUILD → ACTIVE
  - If ERROR: Check fault details
  - Timeout: 30 minutes
- Output: Active server details
- Time: ~10-30 minutes (bare metal provisioning)

**Step 7: Floating IP Assignment**

*Stage 7A: IP Allocation*
- Input: None (or existing pool)
- Actions:
  - Check for unattached floating IPs
  - If available: Reuse
  - If not: Create new from "public" network
- Output: Floating IP address
- Time: ~2 seconds

*Stage 7B: IP Attachment*
- Input: Server ID + Floating IP
- Actions:
  - Call OpenStack compute API
  - Attach floating IP to server
  - Wait for attachment confirmation
- Output: Public IP address
- Time: ~2 seconds

**Step 8: Verification & Output**
- Input: All collected IDs and addresses
- Actions:
  - Get final server details
  - Extract fixed IP (private)
  - Extract floating IP (public)
  - Determine SSH username (ubuntu/centos/etc.)
  - Format connection string
- Output: Display to user + Save to JSON
- Time: ~1 second

**Step 9: Save State**
- Input: All deployment information
- Actions:
  - Create JSON file with all details:
    * server_name, server_id
    * lease_id, reservation_id
    * floating_ip, fixed_ip
    * image_name, image_id
    * node_type, key_name
    * network_id
  - Save to: {server_name}_info.json
- Output: JSON file path
- Time: ~1 second

---

## 3. AI Integration Points (Detailed)

### AI Call #1: Repository Analysis
**Purpose**: Analyze GitHub repository to determine hardware requirements

**Input Structure**:
```
System Prompt: "You are a system administrator analyzing project requirements..."
User Prompt:
  "Analyze these configuration files:
   
   === requirements.txt ===
   torch==2.0.0
   numpy>=1.21.0
   ...
   
   === README.md ===
   # Machine Learning Project
   This project requires GPU support...
   
   Please return JSON with hardware requirements."
```

**Output Structure**:
```json
{
  "cpu_cores": 4,
  "ram_gb": 16,
  "gpu_required": true,
  "gpu_memory_gb": 8,
  "disk_gb": 50,
  "os_type": "ubuntu",
  "os_version": "22.04",
  "cuda_required": true,
  "python_version": "3.9",
  "special_requirements": ["CUDA 11.x", "cuDNN"]
}
```

**Decision Logic**:
- Detects GPU libraries (torch, tensorflow) → gpu_required=true
- Parses version requirements → os_version
- Estimates resource needs based on project size

### AI Call #2: Image Selection (Stage 1)
**Purpose**: Filter candidate images from full list

**Input Structure**:
```
Requirements: {from AI Call #1}
Available Images: [list of ~100 CC-* images]
```

**Output Structure**:
```json
{
  "candidates": [
    "CC-Ubuntu22.04-CUDA",
    "CC-Ubuntu22.04-CUDA-20240326",
    "CC-Ubuntu20.04-CUDA"
  ],
  "reasoning": "Selected CUDA-enabled Ubuntu 22.04 images matching requirements"
}
```

**Decision Logic**:
- Match OS type (ubuntu/centos)
- Match OS version (22.04/20.04)
- Match CUDA requirement
- Prefer recent images
- Return 3-5 candidates

### AI Call #3: Image Selection (Stage 2)
**Purpose**: Select final image from candidates

**Input Structure**:
```
Requirements: {from AI Call #1}
Candidates: [detailed information for 3-5 images]
  - Name, ID, Size, MinDisk, MinRAM, CreatedAt
```

**Output Structure**:
```json
{
  "selected_image": "CC-Ubuntu22.04-CUDA",
  "reasoning": "Latest CUDA image with sufficient resources"
}
```

**Decision Logic**:
- Verify disk/RAM requirements met
- Prefer newer images (created_at)
- Match CUDA version if specified
- Return single best match

### AI Call #4: Lease Duration
**Purpose**: Determine appropriate lease duration

**Input Structure**:
```
Current Time: 2025-12-04 10:30:00
Requirements: {from AI Call #1}
Project Type: Machine Learning Training
```

**Output Structure**:
```json
{
  "duration_hours": 24,
  "reasoning": "ML training typically requires 12-24 hours for convergence"
}
```

**Decision Logic**:
- Consider project complexity
- Default: 24 hours
- Minimum: 1 hour
- Maximum: 168 hours (7 days)
- Factor: GPU vs CPU workloads

---

## 4. Error Handling & Recovery

### Failure Points & Recovery

**Point 1: Repository Clone Failure**
- Error: Git clone fails (network, permissions)
- Recovery: Retry once, then fail gracefully
- User Action: Check URL, try different repo

**Point 2: AI API Failure**
- Error: API timeout, invalid key, rate limit
- Recovery: Use default values
  * Default image: CC-Ubuntu22.04
  * Default duration: 24 hours
  * Default node: compute_cascadelake_r640
- User Action: Check API key in .env

**Point 3: No Available Resources**
- Error: No nodes of requested type available
- Recovery: None (fail with helpful message)
- User Action: Try different node type, different time

**Point 4: Lease Activation Timeout**
- Error: Lease stuck in PENDING after 5 minutes
- Recovery: None (fail, lease will auto-delete)
- User Action: Retry, check Chameleon status page

**Point 5: Server Launch Failure**
- Error: Server enters ERROR state
- Recovery: None (fail with error details)
- User Action: Check quota, retry with different resources

**Point 6: Server Timeout**
- Error: Server stuck in BUILD after 30 minutes
- Recovery: None (fail, suggest manual check)
- User Action: Check console logs, contact support

**Point 7: Floating IP Exhaustion**
- Error: No floating IPs available
- Recovery: Continue without floating IP (warn user)
- User Action: Use internal network or release unused IPs

---

## 5. State Transitions

### Lease State Machine
```
States: CREATING → PENDING → ACTIVE → TERMINATING → TERMINATED
        └──────────→ ERROR

Transitions:
- CREATING → PENDING: Lease submitted to Blazar
- PENDING → ACTIVE: Resources allocated (2-5 min)
- ACTIVE → TERMINATING: End time reached
- TERMINATING → TERMINATED: Resources released
- ANY → ERROR: Allocation failed
```

### Server State Machine
```
States: BUILD → ACTIVE → SHUTOFF → DELETED
        └─────→ ERROR

Transitions:
- BUILD → ACTIVE: Provisioning complete (10-30 min)
- ACTIVE → SHUTOFF: Manual shutdown
- SHUTOFF → ACTIVE: Reboot
- ACTIVE → DELETED: User deletion
- BUILD → ERROR: Provisioning failed
```

---

## 6. Data Flow Diagram Specification

### Entities:
1. User (Human)
2. CLI Tool (provision_v2.py)
3. AI Service (OpenAI-compatible API)
4. OpenStack SDK (envboot/osutil.py)
5. Blazar Service (Reservation system)
6. Nova Service (Compute)
7. Neutron Service (Networking)
8. Glance Service (Images)
9. Chameleon Hardware (Physical servers)

### Data Flows:

**Flow 1: Repository Analysis**
```
User → CLI: GitHub URL
CLI → Git: Clone request
Git → CLI: Repository files
CLI → AI: Files + Analysis request
AI → CLI: Requirements JSON
```

**Flow 2: Image Selection**
```
CLI → Glance: List images request
Glance → CLI: Image list
CLI → AI: Images + Requirements
AI → CLI: Selected image
```

**Flow 3: Resource Provisioning**
```
CLI → Blazar: Create lease request
Blazar → Chameleon: Allocate node
Chameleon → Blazar: Node allocated
Blazar → CLI: Lease ID + Reservation ID
```

**Flow 4: Server Launch**
```
CLI → Nova: Create server request
Nova → Chameleon: Provision bare metal
Chameleon → Nova: Provisioning status
Nova → CLI: Server status updates
```

**Flow 5: Network Setup**
```
CLI → Neutron: Get network ID
Neutron → CLI: Network UUID
CLI → Neutron: Create floating IP
Neutron → CLI: Floating IP address
CLI → Nova: Attach IP to server
Nova → CLI: Attachment confirmed
```

---

## 7. Sequence Diagram Specification

### Main Sequence (Simplified)

```
Actors:
- User
- provision_v2.py
- AI Service
- OpenStack (unified)

Sequence:
1. User → provision_v2.py: run --repo URL
2. provision_v2.py → User: "Analyzing repository..."
3. provision_v2.py → Git: clone URL
4. Git → provision_v2.py: repository files
5. provision_v2.py → AI Service: analyze files
6. AI Service → provision_v2.py: requirements JSON
7. provision_v2.py → User: "Requirements: 4 CPU, 16GB RAM, GPU"
8. provision_v2.py → OpenStack: list images
9. OpenStack → provision_v2.py: image list
10. provision_v2.py → AI Service: select image
11. AI Service → provision_v2.py: "CC-Ubuntu22.04-CUDA"
12. provision_v2.py → User: "Selected image: ..."
13. provision_v2.py → OpenStack: create lease
14. OpenStack → provision_v2.py: lease_id
15. provision_v2.py → User: "Waiting for lease..."
16. Loop: Poll lease status every 10s
17. OpenStack → provision_v2.py: "ACTIVE"
18. provision_v2.py → User: "Lease active"
19. provision_v2.py → OpenStack: launch server
20. OpenStack → provision_v2.py: server_id
21. provision_v2.py → User: "Waiting for server..."
22. Loop: Poll server status every 30s
23. OpenStack → provision_v2.py: "ACTIVE"
24. provision_v2.py → OpenStack: assign floating IP
25. OpenStack → provision_v2.py: floating_ip
26. provision_v2.py → User: "Complete! SSH: ubuntu@192.5.87.31"
```

---

## 8. Component Interaction Matrix

| Component | Interacts With | Purpose | Protocol |
|-----------|----------------|---------|----------|
| provision_v2.py | User | CLI interaction | stdin/stdout |
| provision_v2.py | AI Service | Decision making | HTTPS/JSON |
| provision_v2.py | config.py | Load settings | Python import |
| provision_v2.py | osutil.py | OpenStack access | Python import |
| osutil.py | OpenStack | API calls | REST API |
| AI Service | OpenAI API | LLM inference | HTTPS/JSON |
| Blazar | Nova | Resource hints | Internal API |
| Nova | Chameleon | Hardware control | Ironic API |

---

## 9. Timing Diagram

```
Phase                    | Duration      | Parallel? | User Wait?
-------------------------|---------------|-----------|------------
Configuration Load       | 1s            | No        | Yes
Repository Clone         | 5-30s         | No        | Yes
Requirement Analysis     | 10s (AI)      | No        | Yes
Image Query              | 2s            | No        | Yes
Image Selection          | 10s (AI)      | No        | Yes
Key Management           | 1s            | No        | Yes
Network Query            | 1s            | No        | Yes
Lease Creation           | 2s            | No        | Yes
Lease Activation Wait    | 1-5min        | No        | Yes
Server Launch            | 2s            | No        | Yes
Server Provisioning Wait | 10-30min      | No        | Yes
Floating IP Allocation   | 2s            | No        | Yes
Floating IP Attachment   | 2s            | No        | Yes
State Save               | 1s            | No        | Yes
-------------------------|---------------|-----------|------------
Total (typical)          | 15-40min      |           |
```

---

## 10. Decision Tree Specification

### Image Selection Decision Tree

```
Start: Requirements received
│
├─ GPU Required?
│  ├─ Yes → Filter CUDA images
│  │  ├─ Ubuntu?
│  │  │  ├─ Yes → CC-Ubuntu*-CUDA
│  │  │  └─ No → CC-CentOS*-CUDA
│  │  └─ Version match → Select newest
│  │
│  └─ No → Filter non-CUDA images
│     ├─ Ubuntu?
│     │  ├─ Yes → CC-Ubuntu*
│     │  └─ No → CC-CentOS*
│     └─ Version match → Select newest
│
End: Image selected
```

### Node Type Selection Decision Tree

```
Start: Requirements received
│
├─ GPU Required?
│  ├─ Yes → Check GPU memory
│  │  ├─ > 24GB → gpu_a100
│  │  ├─ > 16GB → gpu_rtx_6000
│  │  └─ ≤ 16GB → gpu_rtx_5000
│  │
│  └─ No → Check CPU/RAM
│     ├─ High RAM (>256GB)?
│     │  └─ Yes → compute_*_384gb
│     ├─ Many cores (>48)?
│     │  └─ Yes → compute_cascadelake_r640
│     └─ Standard → compute_haswell
│
End: Node type selected
```

---

## Summary for Diagram Generation

**Key Diagrams to Create:**

1. **Architecture Diagram** (Layered)
   - 5 layers: User, Application, Intelligence, Integration, Infrastructure
   - Show data flow between layers

2. **Workflow Flowchart** (Linear with branches)
   - 10 main steps
   - Decision points for AI calls
   - Error handling branches

3. **Sequence Diagram** (Time-based)
   - User, CLI, AI, OpenStack actors
   - 26 interactions in sequence
   - Async loops for polling

4. **State Diagram** (Finite state machine)
   - Lease states: 6 states, 5 transitions
   - Server states: 5 states, 6 transitions

5. **Data Flow Diagram** (Entity-relationship)
   - 9 entities
   - 5 major flows
   - REST/Python/Internal protocols

**Suggested Tools:**
- Mermaid.js (for markdown diagrams)
- PlantUML (for UML diagrams)
- Draw.io (for manual diagrams)
- Lucidchart (for collaborative diagrams)

