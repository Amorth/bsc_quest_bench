# BSC Quest Bench - Single-Round Transaction Generation Benchmark

A comprehensive benchmark for evaluating LLM ability to generate accurate blockchain transaction code directly from natural language descriptions in a single attempt.

> **🎯 Pure Natural Language Testing** — No code templates, no implementation hints, just natural language tasks. Tests true understanding, not pattern matching.

## Overview

BSC Quest Bench tests LLM competency in understanding blockchain concepts and generating correct transaction code without iterative feedback. The system evaluates performance across atomic problems (single operations) and composite problems (multi-step workflows).

### Design Philosophy

**Minimal Input, Maximal Reality**

The benchmark uses a **three-part prompt structure** to test pure LLM understanding:

1. **Role Prompt**: Universal blockchain developer role definition
2. **Environment Description**: Complete technical environment specification
3. **Natural Language Task**: Real user-like task descriptions

**No implementation hints, no code templates, no step-by-step guides** — just like real-world scenarios where users describe what they want in natural language.

### Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
cd bsc_quest_bench/skill_runner && bun install && cd ../..

# 2. Run benchmark (normal mode)
python run_quest_bench.py --model gpt-4o --type atomic --max-questions 5

# 3. Run benchmark (naive mode with implementation hints)
python run_quest_bench.py --model gpt-4o --type atomic --max-questions 5 --naive-mode
```

## Key Features

### Core Features
- **Single-Round Evaluation**: Tests LLM's first-attempt accuracy without iteration
- **Pure Natural Language Input**: No code templates, only task descriptions
- **Three-Part Prompt**: Role + Environment + Natural Language Task
- **Difficulty Control**: Toggle between normal and easy mode via `--use-description`
- **Real-World Simulation**: Tests understanding like real user interactions

### Problem Coverage
- **Atomic Problems**: 45 independent blockchain operation tests covering:
  - Native token transfers (BNB)
  - ERC20 token operations
  - NFT operations (ERC721, ERC1155)
  - Contract interactions
  - DeFi operations (swaps, liquidity, staking)
- **Composite Problems**: Multi-step workflows combining atomic operations

### Technical Features
- **Detailed Validators**: Specialized validators for each problem type
- **Deterministic Scoring**: Consistent 100-point scale per problem
- **Environment Isolation**: Complete state reset between tests using Anvil snapshots
- **Local Anvil Fork**: BSC mainnet fork with pre-deployed test contracts
- **Fast Execution**: ~0.002s per test reset using snapshots

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 BSC Quest Bench Flow                        │
└─────────────────────────────────────────────────────────────┘

1. Load problem definition from question bank
   ↓
2. Generate prompt with problem description
   ↓
3. LLM generates TypeScript solution code
   ↓
4. Code executed by Bun/Node runtime
   ↓
5. Transaction object extracted
   ↓
6. Transaction sent to Anvil (local fork)
   ↓
7. Specialized validator checks results
   ↓
8. Score calculated (0-100 points)
   ↓
9. Environment reset via snapshot revert (~0.002s)
   ↓
10. Next problem (if batch mode)
```

## Prompt Design

### Three-Part Structure

BSC Quest Bench uses a **minimal prompt design** to test pure LLM understanding:

```
┌─────────────────────────────────────────────────────────┐
│ Part 1: Role Prompt (Universal)                        │
├─────────────────────────────────────────────────────────┤
│ "You are an expert blockchain developer..."            │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Part 2: Environment Description (Universal)             │
├─────────────────────────────────────────────────────────┤
│ - TypeScript + ethers.js v6                            │
│ - Local Anvil fork of BSC mainnet                       │
│ - Pre-deployed test contracts:                          │
│   • deployedContracts['erc1363_token']                  │
│   • deployedContracts['simple_staking']                 │
│   • deployedContracts['simple_lp_staking']              │
│   • deployedContracts['simple_reward_pool']             │
│   • ... and more                                        │
│ - Technical specifications (EIP-1559, gas, etc.)        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Part 3: Natural Language Task (Question-Specific)       │
├─────────────────────────────────────────────────────────┤
│ "Stake 7.4 CAKE in the single token farming pool        │
│  to start earning"                                       │
└─────────────────────────────────────────────────────────┘
```

### What's NOT in the Prompt (by default)

❌ No code templates  
❌ No implementation steps  
❌ No function signatures  
❌ No ABI definitions  
❌ No hardcoded examples  

The LLM must:
- Understand the environment structure
- Infer which contracts to use from semantic hints
- Generate complete transaction code from scratch

### Difficulty Control

```
┌────────────────────────────────────────────────────────────────────┐
│                        NORMAL MODE (Default)                        │
├────────────────────────────────────────────────────────────────────┤
│ Input:  Role + Environment + Natural Language Task                 │
│ Tests:  Pure understanding and inference ability                   │
│ LLM must infer everything from semantic hints                      │
└────────────────────────────────────────────────────────────────────┘

Command: python run_quest_bench.py --model gpt-4o

┌────────────────────────────────────────────────────────────────────┐
│                      NAIVE MODE (--naive-mode)                      │
├────────────────────────────────────────────────────────────────────┤
│ Input:  Role + Environment + Description + Natural Language Task   │
│ Provides: Technical context, implementation steps, function names  │
│ Use case: Simpler LLMs, debugging, training                        │
└────────────────────────────────────────────────────────────────────┘

Command: python run_quest_bench.py --model gpt-4o --naive-mode
```

#### Mode Comparison

| Aspect | Normal Mode | Naive Mode |
|--------|-------------|------------|
| **Prompt** | 3 parts | 4 parts (adds Description) |
| **Guidance** | None | Step-by-step |
| **Function names** | Not provided | Explicitly stated |
| **Difficulty** | Higher (realistic) | Lower (assisted) |
| **Tests** | Pure understanding | Guided implementation |
| **Suitable for** | Advanced LLMs | All LLMs, debugging |

### Example: How LLM Should Reason

**Input Task**: 
```
"Stake 7.4 CAKE in the single token farming pool"
```

**LLM Reasoning Process**:

```
Step 1: Parse task
  → "single token farming pool" = simple_staking contract

Step 2: Check environment
  → deployedContracts['simple_staking'] = 0x37AB605d...

Step 3: Domain knowledge
  → CAKE token on BSC = 0x0E09FaBB73Bd3Ade...

Step 4: Infer workflow
  → Need to approve staking contract first
  → Then call deposit(amount) function

Step 5: Generate code
  → Check current allowance
  → If insufficient: return approve transaction
  → If sufficient: return deposit transaction
```

**What's NOT provided**:
- ❌ Contract address (must look up in deployedContracts)
- ❌ Function signatures (must know or infer)
- ❌ Approve requirement (must understand ERC20)
- ❌ Implementation steps (must reason through)

**What IS provided**:
- ✅ Environment structure (deployedContracts mapping)
- ✅ Semantic hints ("single token farming pool")
- ✅ Technical environment (ethers.js, EIP-1559, etc.)

### Why This Matters

**Traditional benchmarks often include**:
- Code templates to fill in
- Step-by-step instructions
- Function signatures and examples
- Hardcoded test values

**Result**: Tests pattern matching, not understanding.

**BSC Quest Bench provides**:
- Only natural language descriptions
- Environment specifications
- Semantic hints (not explicit answers)

**Result**: Tests true comprehension and reasoning ability.

**Real-world analogy**:
```
❌ Traditional: "Call approve(0x123..., 1000000) then deposit(1000000)"
✅ Quest Bench: "Stake 7.4 CAKE in the farming pool"
```

The second is how real users communicate. That's what we test.

## Problem Categories

### 1. Native Token Transfers (7 problems)

- `bnb_transfer_basic` - Basic BNB transfer
- `bnb_transfer_percentage` - Transfer percentage of balance
- `bnb_transfer_with_message` - Transfer with data field
- `bnb_transfer_to_contract` - Transfer to contract address
- `bnb_transfer_max_amount` - Transfer maximum available
- `wbnb_deposit` - Wrap BNB to WBNB
- `wbnb_withdraw` - Unwrap WBNB to BNB

### 2. ERC20 Operations (14 problems)

- `erc20_transfer_fixed` - Fixed amount transfer
- `erc20_transfer_percentage` - Percentage transfer
- `erc20_transfer_max_amount` - Maximum amount transfer
- `erc20_approve` - Approve spender
- `erc20_increase_allowance` - Increase allowance
- `erc20_decrease_allowance` - Decrease allowance
- `erc20_revoke_approval` - Revoke approval
- `erc20_burn` - Burn tokens
- `erc20_permit` - ERC2612 signature approval
- `erc20_transferfrom_basic` - TransferFrom operation
- `erc20_transfer_with_callback_1363` - ERC1363 callback transfer
- `erc20_approve_and_call_1363` - ERC1363 approve and call
- `erc20_flashloan` - Flash loan execution

### 3. NFT Operations (6 problems)

- `erc721_transfer` - ERC721 transfer
- `erc721_safe_transfer` - ERC721 safe transfer
- `erc721_approve` - ERC721 approve
- `erc721_set_approval_for_all` - ERC721 global approval
- `erc1155_transfer_single` - ERC1155 single token transfer
- `erc1155_safe_transfer_with_data` - ERC1155 transfer with data

### 4. Contract Interactions (5 problems)

- `contract_call_simple` - Simple contract call
- `contract_call_with_value` - Call with BNB value
- `contract_call_with_params` - Call with parameters
- `contract_delegate_call` - Delegate call
- `contract_payable_fallback` - Payable fallback call

### 5. DeFi Operations (13 problems)

**PancakeSwap Swaps (5 problems)**
- `swap_exact_bnb_for_tokens` - Swap BNB → Token
- `swap_exact_tokens_for_bnb` - Swap Token → BNB
- `swap_exact_tokens_for_tokens` - Swap Token → Token
- `swap_tokens_for_exact_tokens` - Exact output swap
- `swap_multihop_routing` - Multi-hop routing

**PancakeSwap Liquidity (4 problems)**
- `add_liquidity_bnb_token` - Add BNB+Token liquidity
- `add_liquidity_tokens` - Add Token+Token liquidity
- `remove_liquidity_bnb_token` - Remove BNB+Token liquidity
- `remove_liquidity_tokens` - Remove Token+Token liquidity

**Staking/Farming (4 problems)**
- `stake_single_token` - Stake single token
- `stake_lp_tokens` - Stake LP tokens
- `unstake_lp_tokens` - Unstake LP tokens
- `harvest_rewards` - Harvest farming rewards
- `emergency_withdraw` - Emergency withdrawal

## Installation

### Prerequisites

- **Python**: 3.10+
- **Node.js**: 18+ or **Bun**: 1.0+ (recommended)
- **Foundry/Anvil**: Latest version
- **OS**: Ubuntu 22.04+, macOS 12+, or Windows 11 with WSL2

### Step 1: Install Foundry/Anvil

```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
anvil --version
```

### Step 2: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Install TypeScript Runtime & Dependencies

```bash
# Install Bun (recommended)
curl -fsSL https://bun.sh/install | bash

# Install TypeScript dependencies
cd skill_runner
bun install
cd ..
```

## Usage

### Quick Start

```bash
# Default mode (tests pure understanding)
python run_quest_bench.py --model gpt-4o --type atomic

# Naive mode (with implementation guidance)
python run_quest_bench.py --model gpt-4o --type atomic --naive-mode
```

### Run All Atomic Problems

```bash
# Normal difficulty - Pure natural language understanding
python run_quest_bench.py --model gpt-4o --type atomic

# Naive difficulty - Includes implementation hints
python run_quest_bench.py --model gpt-4o --type atomic --naive-mode
```

### Run Random Sample

```bash
# Test 10 random problems (normal mode)
python run_quest_bench.py --model claude-3-sonnet --type atomic --max-questions 10

# Test 10 random problems (naive mode)
python run_quest_bench.py --model claude-3-sonnet --type atomic --max-questions 10 --naive-mode
```

### Run Specific Problems

```bash
# Test specific problems
python run_quest_bench.py \
  --model gemini-pro \
  --questions bnb_transfer_basic swap_exact_bnb_for_tokens erc20_transfer_fixed

# With naive mode
python run_quest_bench.py \
  --model gemini-pro \
  --questions stake_single_token unstake_lp_tokens \
  --naive-mode
```

### Use Custom API Endpoint

```bash
# Azure OpenAI
python run_quest_bench.py \
  --model gpt-4 \
  --base-url https://your-resource.openai.azure.com/ \
  --api-key your-key

# Alibaba Cloud DashScope
python run_quest_bench.py \
  --model qwen-turbo \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --api-key your-key

# OpenRouter
python run_quest_bench.py \
  --model anthropic/claude-sonnet-4 \
  --base-url https://openrouter.ai/api/v1 \
  --api-key your-key
```

### Command Line Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--model` | string | ✅ | LLM model name (e.g., gpt-4o, claude-3-sonnet, gemini-pro) |
| `--type` | string | ❌ | Problem type: `atomic` or `composite` (default: atomic) |
| `--questions` | list | ❌ | Specific question IDs to test (space-separated) |
| `--max-questions` | int | ❌ | Maximum number of random questions to test |
| `--run-index` | int | ❌ | Run index for multiple experiments (default: 0) |
| `--output-dir` | string | ❌ | Results output directory (default: `results/`) |
| `--api-key` | string | ❌ | API key for LLM provider (or set via environment variable) |
| `--base-url` | string | ❌ | Custom API base URL (for Azure, Alibaba Cloud, etc.) |
| `--fork-url` | string | ❌ | BSC RPC URL to fork (default: BSC Testnet) |
| `--naive-mode` | flag | ❌ | **Naive Mode**: Include detailed implementation guidance in prompts |

### Difficulty Modes

| Mode | Flag | Prompt Content | Use Case |
|------|------|----------------|----------|
| **Normal** | (default) | Role + Environment + Natural Language | Standard evaluation, tests pure understanding |
| **Naive** | `--naive-mode` | Role + Environment + **Description** + Natural Language | Simpler LLMs, debugging, training |

## Scoring System

Each atomic problem is scored on a 100-point scale across multiple dimensions:

### Example: BNB Transfer

```
Check 1: Transaction Success    (30 points)
Check 2: Recipient Address      (20 points)
Check 3: Transfer Amount        (20 points)
Check 4: BNB Balance Change     (20 points)
Check 5: Gas Usage              (10 points)
─────────────────────────────────────────────
Total:                          100 points
```

### Scoring Philosophy

- **Strict Validation**: No partial credit for critical failures
- **Key Requirements**: Must pass transaction success + core checks
- **Detailed Feedback**: Each check provides specific error messages
- **Deterministic**: Same code always yields same score

## Project Structure

```
bsc_quest_bench/
├── quest_controller.py           # LLM interaction controller
├── quest_env.py                  # Anvil environment manager
├── quest_executor.py             # Transaction executor
├── parameter_generator.py        # Random parameter generation
├── validators/                   # Specialized validators (46 files)
│   ├── __init__.py
│   ├── bnb_transfer_validator.py
│   ├── erc20_transfer_validator.py
│   ├── swap_exact_bnb_for_tokens_validator.py
│   └── ...
├── question_bank/                # Problem definitions
│   ├── basic_transactions/
│   │   ├── native_transfer/      # 7 BNB transfer problems
│   │   ├── erc20_operations/     # 14 ERC20 problems
│   │   ├── nft_operations/       # 6 NFT problems
│   │   └── contract_call/        # 5 contract problems
│   ├── defi_operations/
│   │   ├── pancakeswap_swap/     # 5 swap problems
│   │   ├── pancakeswap_liquidity/ # 4 liquidity problems
│   │   └── staking_farming/      # 4 staking problems
│   └── advanced_features/
│       ├── delegate_call/        # 1 problem
│       ├── fallback/             # 1 problem
│       └── flashloan/            # 1 problem
├── skill_manager/                # TypeScript executor
│   └── ts_skill_manager.py
├── contracts/                    # Test contracts
│   ├── SimpleStaking.sol         # Single token staking
│   ├── SimpleLPStaking.sol       # LP token staking
│   ├── SimpleRewardPool.sol      # Reward distribution
│   ├── ERC1363Token.sol          # ERC1363 token
│   └── ERC721NFT.sol             # ERC721 NFT
├── run_quest_bench.py            # Main benchmark runner
├── example_usage.py              # Usage examples
├── system_config.json            # System configuration
├── requirements.txt              # Python dependencies
└── README.md                     # This file
```

## Environment & Test Contracts

### Execution Environment

The benchmark runs on a **local Anvil fork** of BSC mainnet:

- ✅ All BSC mainnet contracts accessible (PancakeSwap, USDT, CAKE, etc.)
- ✅ Pre-funded test account with BNB and tokens
- ✅ Pre-deployed test contracts for specialized testing
- ✅ Fast snapshot-based state reset (~0.002s)

### Available Test Contracts

The `deployedContracts` parameter provides access to:

| Key | Contract | Purpose |
|-----|----------|---------|
| `erc1363_token` | ERC1363Token | Test token with callback support (T1363, 18 decimals) |
| `erc1155_token` | ERC1155Multi | Multi-token NFT contract |
| `simple_staking` | SimpleStaking | Single-token staking pool (for CAKE) |
| `simple_lp_staking` | SimpleLPStaking | LP token staking pool |
| `simple_reward_pool` | SimpleRewardPool | Reward distribution with staking |
| `simple_counter` | SimpleCounter | Counter contract for testing |
| `donation_box` | DonationBox | Donation receiver contract |
| `message_board` | MessageBoard | Message storage contract |
| `fallback_receiver` | FallbackReceiver | Fallback function test contract |
| `rich_address` | Pre-funded EOA | Address with pre-approved tokens |

### Contract Usage in Natural Language

LLMs must infer correct contract usage from semantic hints:

| Hint in Task | Inferred Contract |
|--------------|-------------------|
| "single token staking pool" | `deployedContracts['simple_staking']` |
| "SimpleLPStaking", "LP staking" | `deployedContracts['simple_lp_staking']` |
| "SimpleRewardPool", "reward pool" | `deployedContracts['simple_reward_pool']` |
| "ERC1363 token", "T1363" | `deployedContracts['erc1363_token']` |
| "ERC1155 token" | `deployedContracts['erc1155_token']` |

## Results

Results are saved in JSON format:

```
results/quest_bench_{model}_{index}_{timestamp}.json
```

**Example Result:**

```json
{
  "model_name": "gpt-4o",
  "total_score": 4250.0,
  "average_score": 94.4,
  "success_count": 42,
  "failure_count": 3,
  "questions": [
    {
      "question_id": "bnb_transfer_basic",
      "score": 100,
      "max_score": 100,
      "validation_passed": true,
      "execution_success": true
    },
    ...
  ]
}
```

Logs are saved to:

```
log/quest_bench_{model}_{index}_{timestamp}.log
```

## Performance

The system uses Anvil snapshot/revert for fast environment isolation:

- **Initial Setup**: ~27 seconds (one-time)
- **Per-Test Reset**: ~0.002 seconds (snapshot revert)
- **45 Tests Total**: ~2-3 minutes

## Validator Development

Each validator implements a standard interface:

```python
class BaseValidator:
    def validate(
        self,
        tx: Dict[str, Any],           # Transaction object
        receipt: Dict[str, Any],      # Transaction receipt
        state_before: Dict[str, Any], # Pre-transaction state
        state_after: Dict[str, Any]   # Post-transaction state
    ) -> Dict[str, Any]:
        """
        Returns:
        {
            'passed': bool,           # Overall pass/fail
            'score': int,             # Points earned
            'max_score': int,         # Maximum possible
            'checks': List[Dict],     # Individual check results
            'feedback': str           # Detailed feedback
        }
        """
```

## Composite Problems (Upcoming)

Composite problems will test multi-step workflows:

- **Swap + Add Liquidity**: Swap tokens then add to pool
- **Approve + TransferFrom**: Two-step token transfer
- **Stake + Harvest**: Stake tokens and harvest rewards
- **Multi-Protocol Interactions**: Cross-protocol operations

## Troubleshooting

### Environment Reset Issues

If tests pass individually but fail in batch mode:

```python
# Environment automatically resets between tests
# If issues persist, check quest_env.py reset() method
```

### Validator Scoring Issues

```bash
# Check validator logic
python -c "
from bsc_quest_bench.validators import BNBTransferValidator
# Test validator independently
"
```

### Anvil Connection Issues

```bash
# Bypass proxy for localhost
NO_PROXY="localhost,127.0.0.1" python run_quest_bench.py
```

## Design Principles

### 1. Minimal Information, Maximum Reality

**Philosophy**: Test LLMs with only what a real user would provide.

- ✅ Natural language task descriptions
- ✅ Environment specification
- ❌ No code templates
- ❌ No implementation guides
- ❌ No step-by-step instructions

### 2. Pure Understanding Test

**Goal**: Evaluate true comprehension, not pattern matching.

The LLM must:
- Understand blockchain concepts from first principles
- Infer contract usage from semantic hints
- Generate complete working code without examples
- Handle edge cases without explicit warnings

### 3. Inference Over Instruction

**Example**: "Stake 7.4 CAKE in the single token farming pool"

**LLM Must Infer**:
- "single token farming pool" → `deployedContracts['simple_staking']`
- Need to approve tokens first
- CAKE address on BSC mainnet
- Correct function signature and parameters
- Proper gas configuration

**We Don't Tell**:
- Which contract to use
- Function names
- Implementation steps
- ABI definitions

### 4. Real-World Simulation

Task descriptions mimic real user requests:
- ✅ "Transfer 50 USDT to Alice"
- ✅ "Swap 1 BNB for CAKE"
- ✅ "Unstake my LP tokens from the reward pool"
- ❌ "Call transferFrom(address,address,uint256)"
- ❌ "Encode function selector 0xa9059cbb"

### 5. Difficulty Control for Flexibility

- **Default Mode**: Pure natural language (harder)
- **Easy Mode**: Includes implementation guidance (easier)
- **Purpose**: Support different LLM capabilities and use cases

### 6. Deterministic & Reproducible

- Fixed scoring criteria
- Consistent validation logic
- Random parameters but deterministic validation
- Snapshot-based environment reset

## Comparison: Quest Bench vs Gym Env

| Feature | Quest Bench | Gym Env |
|---------|-------------|---------|
| **Evaluation Mode** | Single-round | Multi-round |
| **Focus** | First-attempt accuracy | Learning & exploration |
| **Scoring** | Problem-specific (100pt) | Multi-dimensional (35pts) |
| **Decay Mechanism** | None | Two-level decay |
| **Problem Types** | Atomic + Composite | Open exploration |
| **Use Case** | Skill assessment | Training evaluation |

## FAQ

### Why not include implementation details in the prompt?

**Answer**: To test pure understanding, not pattern matching. Real users don't provide implementation details — they describe what they want in natural language.

### When should I use `--naive-mode`?

**Use naive mode when**:
- Evaluating simpler LLMs
- Debugging failing tests
- Training or fine-tuning models
- Need step-by-step guidance

**Use normal mode (default) when**:
- Standard benchmark evaluation
- Comparing advanced LLMs
- Testing pure understanding capability
- Simulating real user scenarios

### How do LLMs know which test contract to use?

**Answer**: Through semantic reasoning. The environment description lists all available contracts with their purposes. Natural language tasks include hints like "single token staking" → `simple_staking`, "LP staking pool" → `simple_lp_staking`.

### What if my LLM keeps failing certain tests?

1. **Check with naive mode first**: `--naive-mode`
2. **Review error logs**: Detailed logs in `log/` directory
3. **Test individual questions**: Use `--questions` flag
4. **Compare with reference**: Check `docs/prompt_design_philosophy.md`

### How accurate is the scoring?

Very accurate. Each validator:
- Checks transaction success
- Validates state changes
- Verifies function calls
- Compares balances
- Examines event logs

Scoring is deterministic and reproducible.

### Can I add my own test contracts?

Yes! Follow these steps:
1. Deploy contract in `quest_env.py`
2. Add to `deployedContracts` mapping in `quest_controller.py`
3. Update `system_config.json` environment description
4. Create question definition in `question_bank/`
5. Implement validator in `validators/`

See `docs/prompt_design_philosophy.md` for guidelines.

## Documentation

- 📘 [Prompt Design Philosophy](doc/prompt_design_philosophy.md) - Detailed design principles
- 📗 [Architecture Guide](bsc_quest_bench/ARCHITECTURE.md) - System architecture
- 📙 [Changelog](bsc_quest_bench/CHANGELOG.md) - Version history
- 📕 [Query Operations Design](doc/query_operations_design.md) - Query operations specification

## License

MIT License

## Acknowledgments

Built with:
- [Foundry/Anvil](https://github.com/foundry-rs/foundry) - Local EVM simulation
- [ethers.js](https://docs.ethers.org/) - Ethereum library
- [web3.py](https://web3py.readthedocs.io/) - Python Web3 interface
- [Bun](https://bun.sh/) - Fast TypeScript runtime

## Contributing

We welcome contributions! Please:
1. Follow the prompt design philosophy
2. Maintain backward compatibility
3. Add tests for new features
4. Update documentation
