# BSC Quest Bench - Architecture Documentation

## Overview

BSC Quest Bench is a benchmark system for evaluating LLM capabilities in generating blockchain transaction code. The system uses a clean three-part prompt structure to test LLMs without code templates or unnecessary hints.

## Core Design Principles

### 1. Three-Part Prompt Structure

Every test question consists of exactly three parts:

#### Part 1: Role Prompt (Universal)
- Same for all questions
- Defines the AI as a blockchain expert
- Located in: `system_config.json` → `role_prompt`

#### Part 2: Environment Description (Universal)
- Same for all questions
- Explains the TypeScript environment and function signature
- Provides technical requirements
- Located in: `system_config.json` → `environment_description`

#### Part 3: Natural Language Prompt (Question-Specific)
- Unique for each question
- Simulates real user input
- Uses templates with random values
- Located in: question files → `natural_language_templates`

### 2. No Code Templates in Prompts
- The system does NOT provide code templates to the LLM
- The LLM must generate code based on natural language instructions only
- This tests true understanding, not pattern matching

### 3. Random Value Generation
- Each test run generates random parameter values
- Values are generated within reasonable, realistic ranges
- Ensures tests are not memorizable

## File Structure

```
bsc_quest_bench/
├── system_config.json              # Universal role & environment prompts
├── parameter_generator.py          # Random value generation logic
├── quest_controller.py             # Main controller (orchestrates everything)
├── quest_executor.py               # Transaction execution
├── quest_env.py                    # Blockchain environment setup
├── question_bank/                  # Question definitions
│   └── basic_transactions/
│       └── native_transfer/
│           └── bnb_transfer_basic.json
└── validators/                     # Validation logic
    └── bnb_transfer_validator.py
```

## Question Configuration Schema

Each question file (`*.json`) contains:

```json
{
  "id": "unique_question_id",
  "category": "question_category",
  "difficulty": 1,
  "title": "Question Title",
  "description": "Brief description",
  
  "natural_language_templates": [
    "Transfer {amount} to {to_address}",
    "Send {amount} to address {to_address}"
  ],
  
  "parameters": {
    "parameter_name": {
      "type": "address|number|integer|string|boolean",
      "unit": "BNB",  // optional
      "description": "Parameter description",
      "generation": {
        // Generation configuration (see below)
      }
    }
  },
  
  "validation_rules": [
    // Validation rules for grading
  ]
}
```

## Parameter Generation

The `parameter_generator.py` module supports multiple parameter types:

### Address Generation

```json
{
  "type": "address",
  "generation": {
    "method": "random"  // Generates new random address
  }
}
```

Or use a predefined list:

```json
{
  "type": "address",
  "generation": {
    "method": "from_list",
    "addresses": ["0x123...", "0x456..."]
  }
}
```

### Number Generation (Float)

```json
{
  "type": "number",
  "unit": "BNB",
  "generation": {
    "min": 0.001,
    "max": 0.1,
    "decimals": 3
  }
}
```

### Integer Generation

```json
{
  "type": "integer",
  "generation": {
    "min": 1,
    "max": 100
  }
}
```

### String Generation

From a list:

```json
{
  "type": "string",
  "generation": {
    "method": "from_list",
    "values": ["option1", "option2", "option3"]
  }
}
```

Random string:

```json
{
  "type": "string",
  "generation": {
    "method": "random",
    "length": 10,
    "charset": "alphanumeric"  // or "alpha", "numeric", or custom string
  }
}
```

### Boolean Generation

```json
{
  "type": "boolean",
  "generation": {
    "probability": 0.5  // Probability of True
  }
}
```

## Validation System

Validators check if the generated transaction meets requirements. Each validator:

1. Receives generated parameters (not hardcoded values)
2. Validates transaction execution
3. Returns a score and detailed feedback

Example validator initialization:

```python
class MyValidator:
    def __init__(self, to_address: str, amount: float):
        # Parameters match question configuration
        self.expected_to = to_address
        self.expected_amount = amount
```

## Adding New Questions

1. Create a new JSON file in `question_bank/`
2. Define natural language templates
3. Configure parameters with generation rules
4. Create a corresponding validator
5. Link validator in the test runner

Example:

```json
{
  "id": "token_transfer_basic",
  "category": "erc20_transfer",
  "difficulty": 2,
  "title": "Basic ERC20 Token Transfer",
  "description": "Transfer ERC20 tokens between addresses",
  
  "natural_language_templates": [
    "Transfer {amount} {token_symbol} tokens to {to_address}",
    "Send {amount} {token_symbol} to {to_address}"
  ],
  
  "parameters": {
    "to_address": {
      "type": "address",
      "description": "Recipient address",
      "generation": {
        "method": "random"
      }
    },
    "amount": {
      "type": "number",
      "unit": "tokens",
      "description": "Transfer amount",
      "generation": {
        "min": 1,
        "max": 1000,
        "decimals": 2
      }
    },
    "token_symbol": {
      "type": "string",
      "description": "Token symbol",
      "generation": {
        "method": "from_list",
        "values": ["USDT", "USDC", "DAI"]
      }
    }
  },
  
  "validation_rules": [
    // Define validation rules
  ]
}
```

## Flow Diagram

```
1. Load system_config.json
   ↓
2. Load question configuration
   ↓
3. Generate random parameter values
   ↓
4. Fill natural language template with values
   ↓
5. Construct full prompt (role + env + NL prompt)
   ↓
6. Send to LLM
   ↓
7. Extract TypeScript code from response
   ↓
8. Execute code to generate transaction
   ↓
9. Send transaction to blockchain
   ↓
10. Validate result with generated parameters
    ↓
11. Return score and feedback
```

## Key Benefits

1. **No Memorization**: Random values prevent LLMs from memorizing answers
2. **Clean Testing**: No code templates means testing true understanding
3. **Realistic**: Natural language prompts simulate real user requests
4. **Extensible**: Easy to add new question types
5. **Consistent**: Same role and environment for all questions

## Language Policy

- All prompts, logs, and output: **English only**
- No mixed languages in any user-facing content
- Keeps system professional and consistent

