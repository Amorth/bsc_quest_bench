# Changelog - Architecture Refactoring

## Version 2.1.0 (2025-01-20)

### Major Changes

#### 1. Enhanced Environment Description
- **Added**: Complete `deployedContracts` mapping in environment description
- **Added**: Contract naming guidelines and usage instructions
- **Added**: Anvil fork environment description
- **Rationale**: LLM can now infer correct contract addresses from environment info

#### 2. Difficulty Control Mechanism
- **Added**: `--naive-mode` command-line flag
- **Default Mode (Normal)**: Only Role + Environment + Natural Language
  - Tests LLM's pure understanding and inference ability
  - Simulates real user scenarios
- **Naive Mode**: Includes question `description` field
  - Provides step-by-step implementation guidance
  - Suitable for simpler LLMs or debugging

#### 3. Optimized Natural Language Templates
- **Updated**: All staking-related questions with semantic hints
  - `simple_staking` → "single token staking pool"
  - `simple_lp_staking` → "SimpleLPStaking", "LP staking pool"
  - `simple_reward_pool` → "SimpleRewardPool", "reward distribution pool"
- **Updated**: ERC1363 related questions
  - Clearer references to "ERC1363 token", "T1363"
  - Better callback feature descriptions

#### 4. New Documentation
- **Created**: `docs/prompt_design_philosophy.md`
  - Prompt design principles and best practices
  - Natural language template design guidelines
  - Contract naming conventions
  - Difficulty control usage guide

### Bug Fixes
- Fixed issue where LLM couldn't find test contract addresses in `deployedContracts`
- Corrected mismatched contract key names between prompt and actual deployment

### Technical Details
- Modified `QuestController.__init__()` to accept `naive_mode` parameter
- Modified `QuestController._generate_system_prompt()` to conditionally include description
- Updated `QuestBenchRunner` to support difficulty control
- Updated `system_config.json` with comprehensive environment description

### Breaking Changes
- None (backward compatible)
- Default behavior changed: `description` field no longer included in prompts by default
- Use `--naive-mode` flag to restore previous behavior

---

## Version 2.0.0 (2025-11-12)

### Major Changes

#### 1. Three-Part Prompt Structure
- **Before**: Prompts included role, task description, parameter lists, test data, requirements, code templates, and examples
- **After**: Prompts contain only:
  1. Role prompt (universal)
  2. Environment description (universal)
  3. Natural language task (question-specific with random values)

#### 2. Removed Code Templates
- **Before**: System provided complete TypeScript code templates in prompts
- **After**: No code templates provided - LLM must generate code from natural language only
- **Rationale**: Tests true understanding, not pattern matching

#### 3. Random Parameter Generation
- **Before**: Used hardcoded test data from `test_data` field
- **After**: Generates random values within reasonable ranges for each test run
- **Benefits**: 
  - Prevents memorization
  - Tests generalization capability
  - More realistic evaluation

#### 4. Natural Language Templates
- **Before**: Technical descriptions with parameter lists
- **After**: Multiple natural language templates simulating real user requests
- **Example**: "Transfer 0.05 BNB to 0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"

#### 5. English-Only Policy
- **Before**: Mixed Chinese and English in prompts, logs, and output
- **After**: All content in English for consistency and professionalism

### New Files

#### `system_config.json`
Contains universal prompts used for all questions:
- `role_prompt`: Defines AI's role as blockchain expert
- `environment_description`: Explains TypeScript environment and requirements

#### `parameter_generator.py`
Handles random value generation for different parameter types:
- Address generation (random or from list)
- Number generation (with min/max/decimals)
- Integer generation
- String generation (from list or random)
- Boolean generation (with probability)

#### `ARCHITECTURE.md`
Comprehensive documentation of the new architecture:
- Design principles
- File structure
- Question configuration schema
- Parameter generation guide
- How to add new questions

#### `example_usage.py`
Demonstrates the new architecture:
- Loading system config
- Generating random parameters
- Constructing prompts
- Shows what's NOT in prompts

### Modified Files

#### `quest_controller.py`
Major refactoring:
- Added `_load_system_config()`: Loads universal prompts
- Added `_generate_parameters()`: Generates random parameter values
- Added `_generate_natural_language_prompt()`: Fills templates with values
- **Refactored `_generate_system_prompt()`**: 
  - Removed code templates
  - Removed technical requirements
  - Removed test data
  - Now constructs 3-part prompt only
- Updated `run()`: Displays generated parameters and natural language prompt
- Updated `_create_validator()`: Uses generated parameters instead of test data

#### `validators/bnb_transfer_validator.py`
- Changed constructor signature: `(to_address: str, amount: float)` instead of `(expected_to: str, expected_amount: int)`
- Now accepts BNB amount as float (auto-converts to wei)
- Updated all messages to English
- Updated docstrings to English

#### `question_bank/basic_transactions/native_transfer/bnb_transfer_basic.json`
Schema changes:
- Removed `test_data` field
- Added `natural_language_templates` array
- Updated `parameters` with `generation` configuration for each parameter
- Updated all text to English

### Breaking Changes

⚠️ **Important**: This is a breaking change. Old question files and validators are not compatible.

#### Migration Guide

1. **Update Question Files**:
   - Remove `test_data` field
   - Add `natural_language_templates` array
   - Add `generation` config to each parameter
   - Translate all text to English

2. **Update Validators**:
   - Change constructor to accept generated parameters (not test_data)
   - Match parameter names with question configuration
   - Update all messages to English

3. **Update Test Runners**:
   - Remove any hardcoded test data
   - Let system generate random values
   - Use new question schema

### Design Principles

The refactoring follows these core principles:

1. **Separation of Concerns**:
   - Universal prompts in `system_config.json`
   - Question-specific content in question files
   - Parameter generation in dedicated module

2. **No Hardcoding**:
   - No mock data
   - No fallback values
   - No hardcoded test values
   - Everything is either loaded from config or randomly generated

3. **Realistic Testing**:
   - Natural language prompts simulate real users
   - Random values prevent memorization
   - No implementation hints

4. **Extensibility**:
   - Easy to add new parameter types
   - Easy to add new questions
   - Modular validator system

5. **Clean Code**:
   - Single responsibility principle
   - Type hints throughout
   - Comprehensive documentation

### Testing

To test the new architecture:

```bash
# Run example to see prompt construction
python bsc_quest_bench/example_usage.py

# Run actual test (requires blockchain environment)
python -m bsc_quest_bench.quest_controller
```

### Future Enhancements

Potential future improvements:
- Support for complex parameter types (arrays, objects)
- Parameter dependencies (one param affects another)
- Template conditions (show/hide parts based on parameters)
- Multi-step transactions
- Smart contract deployment questions

### Summary

This refactoring creates a cleaner, more principled architecture that:
- ✅ Tests true LLM understanding
- ✅ Prevents memorization through randomization
- ✅ Uses natural language like real users
- ✅ Removes all unnecessary hints and templates
- ✅ Maintains consistency across all questions
- ✅ Is easily extensible for new question types

