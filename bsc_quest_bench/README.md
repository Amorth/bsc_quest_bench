# BSC Quest Bench - Single-Round Transaction Generation Benchmark

A comprehensive benchmark for evaluating LLM ability to generate accurate blockchain transaction code directly from natural language descriptions in a single attempt.

## Overview

BSC Quest Bench tests LLM competency in understanding blockchain concepts and generating correct transaction code without iterative feedback. The system evaluates performance across atomic problems (single operations) and composite problems (multi-step workflows).

## Key Features

- **Single-Round Evaluation**: Tests LLM's first-attempt accuracy without iteration
- **Atomic Problems**: 45 independent blockchain operation tests covering:
  - Native token transfers (BNB)
  - ERC20 token operations
  - NFT operations (ERC721, ERC1155)
  - Contract interactions
  - DeFi operations (swaps, liquidity, staking)
- **Composite Problems**: Multi-step workflows combining atomic operations
- **Detailed Validators**: Specialized validators for each problem type
- **Deterministic Scoring**: Consistent 100-point scale per problem
- **Environment Isolation**: Complete state reset between tests using Anvil snapshots

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
cd skill_manager
# Note: Reuses skill_runner from parent bsc_gym_env if available
cd ..
```

## Usage

### Run All Atomic Problems

```bash
python run_quest_bench.py --model gpt-4o --type atomic
```

### Run Random Sample

```bash
# Test 10 random problems
python run_quest_bench.py --model claude-3-sonnet --type atomic --max-questions 10
```

### Run Specific Problems

```bash
python run_quest_bench.py \
  --model gemini-pro \
  --questions bnb_transfer_basic swap_exact_bnb_for_tokens erc20_transfer_fixed
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
```

### Command Line Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--model` | string | ✅ | LLM model name |
| `--type` | string | ❌ | Problem type: `atomic` or `composite` (default: atomic) |
| `--questions` | list | ❌ | Specific question IDs (space-separated) |
| `--max-questions` | int | ❌ | Random sample size |
| `--run-index` | int | ❌ | Experiment run index (default: 0) |
| `--output-dir` | string | ❌ | Results directory (default: `results/`) |
| `--api-key` | string | ❌ | LLM API key (or use env var) |
| `--base-url` | string | ❌ | Custom API base URL |
| `--fork-url` | string | ❌ | BSC RPC URL (default: BSC Testnet) |

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
│   └── SimpleRewardPool.sol      # Reward distribution
├── contracts_test/               # Additional test contracts
│   ├── TestERC1363Token.sol
│   └── TestERC721NFT.sol
├── run_quest_bench.py            # Main benchmark runner
├── example_usage.py              # Usage examples
├── system_config.json            # System configuration
├── requirements.txt              # Python dependencies
└── README.md                     # This file
```

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

## Comparison: Quest Bench vs Gym Env

| Feature | Quest Bench | Gym Env |
|---------|-------------|---------|
| **Evaluation Mode** | Single-round | Multi-round |
| **Focus** | First-attempt accuracy | Learning & exploration |
| **Scoring** | Problem-specific (100pt) | Multi-dimensional (35pts) |
| **Decay Mechanism** | None | Two-level decay |
| **Problem Types** | Atomic + Composite | Open exploration |
| **Use Case** | Skill assessment | Training evaluation |

## License

MIT License

## Acknowledgments

Built with:
- [Foundry/Anvil](https://github.com/foundry-rs/foundry) - Local EVM simulation
- [ethers.js](https://docs.ethers.org/) - Ethereum library
- [web3.py](https://web3py.readthedocs.io/) - Python Web3 interface
- [Bun](https://bun.sh/) - Fast TypeScript runtime
