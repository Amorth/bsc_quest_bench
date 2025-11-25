"""
BSC Quest Controller - Control Layer

Responsibilities:
1. Manage LLM input/output
2. Coordinate layer interactions (Environment, Executor, Validator)
3. Extract TypeScript code blocks
4. Save scoring metrics
"""

import json
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

from bsc_quest_bench.quest_env import QuestEnvironment
from bsc_quest_bench.quest_executor import QuestExecutor
from bsc_quest_bench.parameter_generator import ParameterGenerator, format_parameter_value


class QuestController:
    """Quest Controller - Coordinate single round transaction generation evaluation"""
    
    def __init__(
        self,
        model_name: str,
        question_path: str,
        validator_class,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        fork_url: str = "https://bsc-testnet.drpc.org",
            test_mode: bool = False,
            test_code_path: Optional[str] = None,
            env: Optional[QuestEnvironment] = None,
            naive_mode: bool = False
    ):
        """
        Initialize controller
        
        Args:
            model_name: LLM model name (e.g., "anthropic/claude-sonnet-4", "gpt-4")
            question_path: Path to question configuration file
            validator_class: Validator class
            api_key: API key (use environment variable if None)
            base_url: Custom API base URL (optional)
            fork_url: BSC RPC URL (default: testnet)
            test_mode: Test mode, use pre-written code instead of calling LLM
            test_code_path: Path to test code (only valid in test mode)
            env: Optional existing QuestEnvironment instance (for reusing Anvil)
            naive_mode: Naive mode, include question description in prompt (default False, controls difficulty)
        """
        self.model_name = model_name
        self.question_path = question_path
        self.validator_class = validator_class
        self.api_key = api_key
        self.base_url = base_url
        self.fork_url = fork_url
        self.test_mode = test_mode
        self.test_code_path = test_code_path
        self.reuse_env = env  # Reusable environment instance
        self.naive_mode = naive_mode  # Whether to use Naive mode
        
        # Load system config
        self.system_config = self._load_system_config()
        
        # Load question config
        self.question = self._load_question()
        
        # Initialize parameter generator
        self.param_generator = ParameterGenerator()
        
        # Generate random parameter values
        self.generated_params = self._generate_parameters()
        
        # Initialize LLM
        self.llm = self._init_llm(model_name, api_key, base_url)
        
        # Store results
        self.result = {
            'question_id': self.question['id'],
            'model_name': model_name,
            'start_time': None,
            'end_time': None,
            'generated_params': self.generated_params,
            'natural_language_prompt': None,
            'llm_response': None,
            'extracted_code': None,
            'execution_success': False,
            'validation_result': None,
            'error': None
        }
    
    def _get_lp_token_address(self, env, token0: str, token1: str) -> str:
        """
        Get LP token address for a Pancake pair
        
        Args:
            env: QuestEnvironment instance
            token0: First token address
            token1: Second token address
            
        Returns:
            LP token (pair) address
        """
        from eth_utils import to_checksum_address
        
        # PancakeSwap Factory address on BSC
        factory_address = '0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73'
        
        try:
            # Use the Web3 instance from env
            w3 = env.w3
            
            # getPair(address tokenA, address tokenB) returns (address pair)
            # Function selector: 0xe6a43905
            token0_checksum = to_checksum_address(token0)
            token1_checksum = to_checksum_address(token1)
            
            data = '0xe6a43905' + \
                   token0_checksum[2:].rjust(64, '0') + \
                   token1_checksum[2:].rjust(64, '0')
            
            result = w3.eth.call({
                'to': to_checksum_address(factory_address),
                'data': data
            })
            
            # Extract address from result (last 20 bytes)
            pair_address = '0x' + result.hex()[-40:]
            return pair_address.lower()
            
        except Exception as e:
            print(f"Warning: Could not get LP token address: {e}")
            return None
    
    def _load_system_config(self) -> Dict[str, Any]:
        """Load system configuration (role and environment prompts)"""
        config_file = Path(__file__).parent / 'system_config.json'
        if not config_file.exists():
            raise FileNotFoundError(f"System configuration file not found: {config_file}")
        
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _load_question(self) -> Dict[str, Any]:
        """Load question configuration"""
        question_file = Path(self.question_path)
        if not question_file.exists():
            raise FileNotFoundError(f"Question configuration file not found: {self.question_path}")
        
        with open(question_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _generate_parameters(self) -> Dict[str, Any]:
        """Generate random parameter values based on question configuration"""
        if not self.question.get('parameters'):
            return {}
        
        return self.param_generator.generate_parameters(self.question['parameters'])
    
    def _regenerate_env_parameters(self, env):
        """
        Regenerate parameters requiring environment (method='from_env')
        
        Args:
            env: QuestEnvironment instance
        """
        params_config = self.question.get('parameters', {})
        
        # Check if any parameters need to be fetched from environment
        has_env_params = False
        env_param_names = []
        for param_name, param_config in params_config.items():
            generation_config = param_config.get('generation', {})
            if generation_config.get('method') == 'from_env':
                has_env_params = True
                env_param_names.append(param_name)
        
        if not has_env_params:
            return
        
        print(f"🔄 Regenerating environment parameters: {', '.join(env_param_names)}")
        
        # Recreate parameter generator with environment
        env_param_generator = ParameterGenerator(environment=env)
        
        # Only regenerate parameters that require environment (from_env method)
        # Keep other parameters (especially random ones) unchanged
        new_params = {}
        for param_name, param_config in params_config.items():
            generation_config = param_config.get('generation', {})
            if generation_config.get('method') == 'from_env':
                # Regenerate this parameter
                single_param_config = {param_name: param_config}
                regenerated = env_param_generator.generate_parameters(single_param_config)
                new_params[param_name] = regenerated[param_name]
            # else: keep the original value (don't regenerate random parameters)
        
        # Display updated parameters
        for param_name in env_param_names:
            old_value = self.generated_params.get(param_name, 'N/A')
            new_value = new_params.get(param_name, 'N/A')
            if isinstance(old_value, str) and len(old_value) > 10:
                old_display = old_value[:10] + '...'
            else:
                old_display = str(old_value)
            print(f"  • {param_name}: {old_display} → {new_value}")
        
        # Update only the regenerated parameters
        self.generated_params.update(new_params)
        
        # Regenerate natural language prompt
        self.result['natural_language_prompt'] = self._generate_natural_language_prompt()
        print()
    
    def _init_llm(
        self,
        model_name: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        """
        Initialize LLM client
        
        Args:
            model_name: Model name
            api_key: API key
            base_url: Custom API base URL
            
        Returns:
            LLM client instance
        """
        if not model_name:
            raise ValueError("Model name cannot be empty")
        
        llm_kwargs = {'model': model_name, 'temperature': 0.7}
        
        # Priority 1: Custom base_url
        if base_url:
            print(f"🔄 Using custom API: {base_url}")
            print(f"   Model: {model_name}")
            if api_key:
                llm_kwargs['api_key'] = api_key
            llm_kwargs['base_url'] = base_url
            return ChatOpenAI(**llm_kwargs)
        
        # Priority 2: OpenRouter (model name contains '/')
        if '/' in model_name:
            print(f"🔄 Using OpenRouter")
            print(f"   Model: {model_name}")
            if api_key:
                llm_kwargs['api_key'] = api_key
                if not api_key.startswith('sk-or-v1-'):
                    print(f"⚠️  Warning: OpenRouter API key usually starts with 'sk-or-v1-'")
                    print(f"   Your key starts with: {api_key[:10]}...")
            else:
                print(f"⚠️  Warning: OpenRouter API key not provided")
            
            llm_kwargs['base_url'] = "https://openrouter.ai/api/v1"
            llm_kwargs['default_headers'] = {
                "HTTP-Referer": "https://github.com/bsc-quest-bench",
                "X-Title": "BSC Quest Bench"
            }
            return ChatOpenAI(**llm_kwargs)
        
        # Priority 3: Standard provider
        if 'gpt' in model_name.lower() or 'openai' in model_name.lower():
            if api_key:
                llm_kwargs['openai_api_key'] = api_key
            return ChatOpenAI(**llm_kwargs)
        elif 'claude' in model_name.lower() or 'anthropic' in model_name.lower():
            if api_key:
                llm_kwargs['anthropic_api_key'] = api_key
            return ChatAnthropic(**llm_kwargs)
        elif 'gemini' in model_name.lower() or 'google' in model_name.lower():
            if api_key:
                llm_kwargs['google_api_key'] = api_key
            return ChatGoogleGenerativeAI(**llm_kwargs)
        else:
            if api_key:
                llm_kwargs['openai_api_key'] = api_key
            return ChatOpenAI(**llm_kwargs)
    
    def _generate_natural_language_prompt(self) -> str:
        """Generate natural language prompt with filled parameters"""
        templates = self.question.get('natural_language_templates', [])
        if not templates:
            raise ValueError("No natural language templates defined for this question")
        
        # Choose a random template
        import random
        template = random.choice(templates)
        
        # Fill in the parameters
        for param_name, param_value in self.generated_params.items():
            param_config = self.question['parameters'][param_name]
            formatted_value = format_parameter_value(param_value, param_config)
            template = template.replace(f"{{{param_name}}}", formatted_value)
        
        return template
    
    def _generate_system_prompt(self) -> str:
        """
        Generate system prompt with three or four parts:
        1. Role prompt (same for all questions)
        2. Environment description (same for all questions)
        3. Question-specific context (optional, ONLY if naive_mode=True)
        4. Natural language prompt (unique per question, with random values)
        
        By default (naive_mode=False), only parts 1, 2, and 4 are used.
        This keeps the prompt minimal and tests the LLM's pure understanding ability.
        Naive mode (naive_mode=True) includes detailed implementation guidance.
        """
        # Part 1: Role prompt (supports list or string format)
        role_prompt_raw = self.system_config['role_prompt']
        role_prompt = '\n'.join(role_prompt_raw) if isinstance(role_prompt_raw, list) else role_prompt_raw
        
        # Part 2: Environment description (supports list or string format)
        env_description_raw = self.system_config['environment_description']
        env_description = '\n'.join(env_description_raw) if isinstance(env_description_raw, list) else env_description_raw
        
        # Part 3: Question-specific context (optional, controlled by naive_mode flag)
        question_context = ""
        if self.naive_mode and 'description' in self.question:
            description_raw = self.question['description']
            description = '\n'.join(description_raw) if isinstance(description_raw, list) else description_raw
            question_context = f"\n\nContext for this task:\n{description}"
        
        # Part 4: Natural language prompt with random values
        natural_language_prompt = self._generate_natural_language_prompt()
        
        # Store the natural language prompt for logging
        self.result['natural_language_prompt'] = natural_language_prompt
        
        # Combine all parts
        full_prompt = f"{role_prompt}\n\n{env_description}{question_context}\n\nTask:\n{natural_language_prompt}"
        
        return full_prompt
    
    def extract_code_blocks(self, text: str) -> List[str]:
        """
        Extract code blocks
        
        Args:
            text: LLM response text
            
        Returns:
            List of code blocks
        """
        pattern = r'```(?:typescript|ts|javascript|js)?\s*\n(.*?)```'
        matches = re.findall(pattern, text, re.DOTALL)
        return [match.strip() for match in matches if match.strip()]
    
    def _load_test_code(self) -> str:
        """
        Load test code and replace parameter placeholders
        
        Returns:
            Code after parameter replacement
        """
        if not self.test_code_path:
            raise ValueError("Test mode enabled but no test_code_path provided")
        
        # Read test code
        with open(self.test_code_path, 'r', encoding='utf-8') as f:
            code = f.read()
        
        # Replace parameter placeholders
        for param_name, param_value in self.generated_params.items():
            placeholder = f"{{{{{param_name}}}}}"  # {{param_name}}
            # Use format_parameter_value for type-aware formatting
            param_config = self.question['parameters'][param_name]
            formatted_value = format_parameter_value(param_value, param_config)
            code = code.replace(placeholder, formatted_value)
        
        return code
    
    def _save_code_to_temp_file(self, code: str) -> str:
        """
        Save code to temporary file
        
        Args:
            code: TypeScript code
            
        Returns:
            Temporary file path
        """
        # Use skill_runner/temp/ directory instead of system /tmp/
        # So Bun can correctly resolve node_modules
        timestamp = int(time.time() * 1000)
        project_root = Path(__file__).parent.parent
        temp_dir = project_root / 'bsc_quest_bench' / 'skill_runner' / 'temp'
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        code_file = temp_dir / f'temp_skill_{timestamp}.ts'
        
        with open(code_file, 'w', encoding='utf-8') as f:
            f.write(code)
        
        return str(code_file)
    
    async def run(self) -> Dict[str, Any]:
        """
        Run evaluation (single-round for atomic, multi-round for composite)
        
        Returns:
            Evaluation result dictionary
        """
        # Check if this is a composite problem
        is_composite = self.question.get('category') == 'composite_problems'
        
        # In test mode, always use single-turn evaluation (even for composite problems)
        if self.test_mode:
            print(f"🧪 Test Mode: Using test script instead of LLM")
            return await self.run_single_turn()
        
        if is_composite:
            # Multi-round LLM evaluation for composite problems
            return await self.run_multi_turn()
        else:
            # Single-round evaluation for atomic problems
            return await self.run_single_turn()
    
    async def run_single_turn(self) -> Dict[str, Any]:
        """
        Run single round evaluation (for atomic problems)
        
        Returns:
            Evaluation result dictionary
        """
        print("="*80)
        print("BSC Quest Bench - Single Round Evaluation")
        print("="*80)
        print(f"Question ID: {self.question['id']}")
        print(f"Model: {self.model_name}")
        print(f"Difficulty: {self.question['difficulty']}")
        print("="*80)
        print()
        
        self.result['start_time'] = datetime.now().isoformat()
        
        # 1. Start or reuse environment
        should_stop_env = False  # Flag to stop environment in finally
        if self.reuse_env:
            print("🔧 Reusing existing environment...")
            env = self.reuse_env
            env_info = {
                'rpc_url': f'http://127.0.0.1:{env.anvil_port}',
                'chain_id': env.chain_id,
                'test_address': env.test_address,
                'test_private_key': env.test_account.key.hex(),
                # Get deployed contract addresses from environment object
                'simple_staking_address': getattr(env, 'simple_staking_address', None),
                'simple_lp_staking_address': getattr(env, 'simple_lp_staking_address', None),
                'simple_reward_pool_address': getattr(env, 'simple_reward_pool_address', None),
                'erc1363_token_address': getattr(env, 'erc1363_token_address', None),
                'erc1155_token_address': getattr(env, 'erc1155_token_address', None),
                'flashloan_contract_address': getattr(env, 'flashloan_contract_address', None),
                'simple_counter_address': getattr(env, 'simple_counter_address', None),
                'donation_box_address': getattr(env, 'donation_box_address', None),
                'message_board_address': getattr(env, 'message_board_address', None),
                'proxy_address': getattr(env, 'proxy_address', None),
                'implementation_address': getattr(env, 'implementation_address', None),
                'fallback_receiver_address': getattr(env, 'fallback_receiver_address', None),
                'rich_address': getattr(env, 'rich_address', None),
                'erc721_test_nft_address': getattr(env, 'erc721_test_nft_address', None),
            }
            print()
        else:
            print("🔧 Starting new environment...")
            env = QuestEnvironment(fork_url=self.fork_url)
            env_info = env.start()
            should_stop_env = True  # Newly started environment needs to be stopped in finally
            print()
        
        # 1.5 Regenerate parameters requiring environment (e.g. from_env)
        self._regenerate_env_parameters(env)
        
        try:
            # 2. Display generated parameters
            print("📝 Generated Natural Language Prompt:")
            if not self.test_mode:
                system_prompt = self._generate_system_prompt()
                print(f"   \"{self.result['natural_language_prompt']}\"")
            else:
                print(f"   [TEST MODE - Skipped]")
            
            print(f"\n📊 Generated Parameters:")
            for param_name, param_value in self.generated_params.items():
                print(f"   - {param_name}: {param_value}")
            print()
            
            # 3. Get code: Test mode or LLM generation
            if self.test_mode:
                # Test mode: Load code from file
                print("🧪 TEST MODE: Loading code from test file...")
                code = self._load_test_code()
                self.result['llm_response'] = "[TEST MODE] Code loaded from file"
                self.result['extracted_code'] = code
                print(f"✅ Test code loaded from: {self.test_code_path}")
                print()
            else:
                # Normal mode: Call LLM
                print("🤖 Calling LLM to generate code...")
                messages = [
                    SystemMessage(content=system_prompt)
                ]
                
                response = await self.llm.ainvoke(messages)
                self.result['llm_response'] = response.content
                
                print(f"✅ LLM response received ({len(response.content)} characters)")
                print()
                
                # 4. Extract code blocks
                print("📝 Extracting code blocks...")
                code_blocks = self.extract_code_blocks(response.content)
                
                if not code_blocks:
                    error_msg = "TypeScript code block not found"
                    print(f"❌ {error_msg}")
                    self.result['error'] = error_msg
                    return self.result
                
                code = code_blocks[0]
                self.result['extracted_code'] = code
                print(f"✅ Extracted {len(code_blocks)} code blocks")
                print()
            
            print("─"*80)
            print("Extracted Code:")
            print("─"*80)
            print(code)
            print("─"*80)
            print()
            
            # 5. Setup for query operations BEFORE executing code (set random balance if needed)
            operation_type = self.question.get('metadata', {}).get('operation_type')
            if operation_type == 'query':
                self._setup_query_operation(env, self.generated_params)
            
            # 5.5 Setup for composite_approve_transferfrom: pre-set allowance
            if self.question.get('id') == 'composite_approve_transferfrom':
                print("🔧 Setting up allowance for composite_approve_transferfrom...")
                token_address = self.generated_params.get('token_address')
                from_address = self.generated_params.get('from_address')  # agent
                spender_address = self.generated_params.get('spender_address')  # also agent in this case
                amount = self.generated_params.get('amount', 50.0)
                token_decimals = self.generated_params.get('token_decimals', 18)
                
                # Set allowance to 2x the amount to allow transferFrom and still show decrease
                allowance_amount_wei = int(amount * 2 * (10 ** token_decimals))
                
                success = self._set_erc20_allowance_via_approve(
                    env,
                    token_address,
                    from_address,
                    spender_address,
                    allowance_amount_wei
                )
                
                if success:
                    print(f"   ✅ Allowance set: {amount * 2} tokens (2x transfer amount)")
                else:
                    print(f"   ⚠️  Warning: Failed to set allowance")
                print()
            
            # 6. Execute code to generate transaction object
            print("⚙️  Executing TypeScript code...")
            from .skill_manager.ts_skill_manager import TypeScriptSkillManager
            
            skill_manager = TypeScriptSkillManager(use_bun=True)
            code_file = self._save_code_to_temp_file(code)
            
            try:
                # Construct deployed contracts dictionary
                deployed_contracts = {
                    'simple_staking': env_info.get('simple_staking_address'),
                    'simple_lp_staking': env_info.get('simple_lp_staking_address'),
                    'simple_reward_pool': env_info.get('simple_reward_pool_address'),
                    'erc1363_token': env_info.get('erc1363_token_address'),
                    'erc1155_token': env_info.get('erc1155_token_address'),
                    'flashloan_contract': env_info.get('flashloan_contract_address'),
                    'simple_counter': env_info.get('simple_counter_address'),
                    'donation_box': env_info.get('donation_box_address'),
                    'message_board': env_info.get('message_board_address'),
                    'proxy': env_info.get('proxy_address'),
                    'implementation': env_info.get('implementation_address'),
                    'fallback_receiver': env_info.get('fallback_receiver_address'),
                    'rich_address': env_info.get('rich_address')  # For transferFrom tests
                }
                # Remove None values
                deployed_contracts = {k: v for k, v in deployed_contracts.items() if v is not None}
                
                tx_result = skill_manager.execute_skill(
                    code_file=code_file,
                    provider_url=env_info['rpc_url'],
                    agent_address=env_info['test_address'],
                    deployed_contracts=deployed_contracts
                )
                
                if not tx_result.get('success'):
                    error_msg = tx_result.get('error', 'Unknown error')
                    print(f"❌ TypeScript execution failed: {error_msg}")
                    self.result['error'] = error_msg
                    return self.result
                
                tx = tx_result['tx_object']
                print(f"✅ Transaction object generated successfully")
                print(f"   To: {tx.get('to')}")
                print(f"   Value: {tx.get('value')}")
                print()
                
            finally:
                import os
                if os.path.exists(code_file):
                    os.unlink(code_file)
            
            # 7. Create executor and execute transaction
            print("🔗 Executing transaction...")
            executor = QuestExecutor(
                w3=env.w3,
                private_key=env_info['test_private_key']
            )
            
            # Create validator
            validator = self._create_validator(self.generated_params)
            
            # Prepare token related parameters (if ERC20 or WBNB operation)
            token_address = None
            target_address_for_token = None
            token_out_address = None
            spender_address = None
            lp_token_address = None
            pool_address = None
            from_address = None
            nft_address = None
            nft_token_id = None
            operator_address = None
            nft_type = None
            counter_contract_address = None
            message_board_contract_address = None
            proxy_address = None
            implementation_address = None
            expected_value = None
            
            # Special handling for composite problems
            if self.question.get('category') == 'composite_problems':
                # Extract token_address from transaction
                token_address = tx.get('to')  # The contract being called
                
                tx_data = tx.get('data', '')
                
                # Extract parameters based on function selector
                # transfer(address to, uint256 amount) - selector: 0xa9059cbb
                if tx_data and tx_data.startswith('0xa9059cbb') and len(tx_data) >= 138:
                    # Extract to_address (bytes 4-36 after selector)
                    to_address_hex = '0x' + tx_data[34:74]  # Remove leading zeros
                    from eth_utils import to_checksum_address
                    target_address_for_token = to_checksum_address(to_address_hex)
                    print(f"🔗 Composite problem (transfer) detected:")
                    print(f"   Token address: {token_address}")
                    print(f"   Target address: {target_address_for_token}")
                
                # approve(address spender, uint256 amount) - selector: 0x095ea7b3
                elif tx_data and tx_data.startswith('0x095ea7b3') and len(tx_data) >= 138:
                    # Extract spender_address (bytes 4-36 after selector)
                    spender_hex = '0x' + tx_data[34:74]  # Remove leading zeros
                    from eth_utils import to_checksum_address
                    spender_address = to_checksum_address(spender_hex)
                    print(f"🔗 Composite problem (approve) detected:")
                    print(f"   Token address: {token_address}")
                    print(f"   Spender address: {spender_address}")
                
                # transferFrom(address from, address to, uint256 tokenId/amount) - selector: 0x23b872dd
                # This could be ERC721 or ERC20 transferFrom - need to distinguish by atomic_operations
                elif tx_data and tx_data.startswith('0x23b872dd') and len(tx_data) >= 202:
                    # Check if this is ERC20 or ERC721 by looking at atomic_operations
                    composite_structure = self.question.get('composite_structure', {})
                    atomic_ops = [op.get('atomic_id') for op in composite_structure.get('atomic_operations', [])]
                    
                    if 'erc20_transferfrom_basic' in atomic_ops:
                        # ERC20 transferFrom
                        # Extract from_address (bytes 4-36 after selector)
                        from_address_hex = '0x' + tx_data[34:74]
                        from eth_utils import to_checksum_address
                        from_address = to_checksum_address(from_address_hex)
                        
                        # Extract to_address (bytes 36-68 after selector)
                        to_address_hex = '0x' + tx_data[98:138]
                        target_address_for_token = to_checksum_address(to_address_hex)
                        
                        # Spender is the agent (executing the transferFrom)
                        spender_address = self.generated_params.get('spender_address') or env_info.get('test_address')
                        
                        print(f"🔗 Composite problem (ERC20 transferFrom) detected:")
                        print(f"   Token address: {token_address}")
                        print(f"   From address: {from_address}")
                        print(f"   Target address: {target_address_for_token}")
                        print(f"   Spender address (agent): {spender_address}")
                    elif 'erc721_transfer' in atomic_ops:
                        # NFT transfer (ERC721 transferFrom)
                        # Extract tokenId (bytes 68-100 after selector)
                        token_id_hex = tx_data[138:202]
                        nft_token_id = int(token_id_hex, 16)
                        nft_address = token_address
                        nft_type = 'erc721'
                        print(f"🔗 Composite problem (NFT transfer) detected:")
                        print(f"   NFT address: {nft_address}")
                        print(f"   Token ID: {nft_token_id}")
                    else:
                        print(f"⚠️  Unknown transferFrom type")
                        target_address_for_token = self.generated_params.get('to_address')
                
                # deposit(uint256 _amount) - selector: 0xb6b55f25 (Staking)
                elif tx_data and tx_data.startswith('0xb6b55f25') and len(tx_data) >= 74:
                    # Staking deposit
                    pool_address = tx.get('to', '')
                    token_address = self.generated_params.get('token_address', '')
                    print(f"🔗 Composite problem (Staking) detected:")
                    print(f"   Pool address: {pool_address}")
                    print(f"   Token address: {token_address}")
                
                # swapExactETHForTokens - selector: 0x7ff36ab5 (PancakeSwap Swap)
                elif tx_data and tx_data.startswith('0x7ff36ab5'):
                    # Swap BNB for tokens
                    token_address = self.generated_params.get('token_address', '')
                    token_out_address = token_address  # Output token
                    value = tx.get('value', 0)
                    if isinstance(value, str):
                        value = int(value)
                    print(f"🔗 Composite problem (Swap BNB->Token) detected:")
                    print(f"   Router address: {tx.get('to', '')}")
                    print(f"   Token out: {token_out_address}")
                    print(f"   BNB amount: {value / 10**18:.6f} BNB")
                
                # deposit() - selector: 0xd0e30db0 (WBNB Deposit)
                elif tx_data and tx_data.startswith('0xd0e30db0'):
                    # WBNB deposit (wrap BNB)
                    wbnb_address = tx.get('to', '')
                    token_address = wbnb_address  # WBNB is the token
                    value = tx.get('value', 0)
                    if isinstance(value, str):
                        value = int(value)
                    print(f"🔗 Composite problem (WBNB Deposit) detected:")
                    print(f"   WBNB address: {wbnb_address}")
                    print(f"   BNB amount: {value / 10**18:.6f} BNB")
                
                # harvest() - selector: 0x4641257d (Harvest Rewards)
                elif tx_data and tx_data.startswith('0x4641257d'):
                    # Harvest rewards
                    pool_address = tx.get('to', '')
                    token_address = self.generated_params.get('reward_token_address', '')
                    print(f"🔗 Composite problem (Harvest Rewards) detected:")
                    print(f"   Pool address: {pool_address}")
                    print(f"   Reward token address: {token_address}")
                
                else:
                    # Fallback to generated params
                    target_address_for_token = self.generated_params.get('to_address')
                    spender_address = self.generated_params.get('spender_address')
                    nft_address = self.generated_params.get('nft_address')
                    nft_token_id = self.generated_params.get('token_id')
                    if nft_address and nft_token_id is not None:
                        nft_type = 'erc721'
                    print(f"🔗 Composite problem detected:")
                    print(f"   Token address: {token_address}")
                    print(f"   Target/Spender address: {target_address_for_token or spender_address}")
            
            # Special handling: erc20_transferfrom_basic needs to be checked before erc20_operations
            elif self.question.get('id') == 'erc20_transferfrom_basic':
                # TransferFrom: track from_address balance, to_address balance, and allowance
                token_address = self.generated_params.get('token_address')
                from_address = self.generated_params.get('from_address')  # from_address (token owner) - for validation
                target_address_for_token = self.generated_params.get('to_address')  # to_address (recipient) - for validation
                spender_address = self.generated_params.get('agent_address')  # agent is the approved spender
                
                # Decode actual addresses from transaction data for state tracking
                # transferFrom(address from, address to, uint256 amount)
                # Data layout: 0x + 8 (selector) + 64 (from) + 64 (to) + 64 (amount)
                tx_data = tx.get('data', '')
                if isinstance(tx_data, str) and tx_data.startswith('0x23b872dd') and len(tx_data) >= 202:
                    try:
                        # Extract from_address (bytes 4-36, but padded to 64 hex chars)
                        from_hex = tx_data[10:74]  # Skip '0x23b872dd', take next 64 chars
                        actual_from = '0x' + from_hex[-40:]  # Last 40 chars = 20 bytes = address
                        
                        # Extract to_address (bytes 36-68, padded to 64 hex chars)
                        to_hex = tx_data[74:138]  # Next 64 chars
                        actual_to = '0x' + to_hex[-40:]  # Last 40 chars = address
                        
                        print(f"🔍 Decoded addresses from transaction data:")
                        print(f"   From (owner): {actual_from}")
                        print(f"   To (recipient): {actual_to}")
                        print(f"   Spender (agent): {spender_address}")
                        
                        # Compare with generated parameters
                        if actual_from.lower() != self.generated_params.get('from_address', '').lower():
                            print(f"   ⚠️  from_address mismatch! Generated: {self.generated_params.get('from_address')}")
                        if actual_to.lower() != self.generated_params.get('to_address', '').lower():
                            print(f"   ⚠️  to_address mismatch! Generated: {self.generated_params.get('to_address')}")
                        
                        # Use actual addresses for state tracking
                        from_address = actual_from
                        target_address_for_token = actual_to
                    except Exception as e:
                        print(f"⚠️  Failed to decode addresses from tx data: {e}")
                        print(f"   Using generated parameters instead")
            elif self.question.get('subcategory') == 'erc20_operations':
                # Special handling for erc20_permit: needs to track allowance
                if self.question.get('id') == 'erc20_permit':
                    token_address = self.generated_params.get('token_address')
                    spender_address = self.generated_params.get('spender_address')
                    # Note: For permit, we track allowance between owner and spender
                else:
                    token_address = self.generated_params.get('token_address')
                    target_address_for_token = self.generated_params.get('to_address')
                    spender_address = self.generated_params.get('spender_address')
            elif self.question.get('subcategory') == 'pancakeswap_swap':
                # PancakeSwap swap needs to track token balance and allowance
                # For BNB → Token and Token → Token swaps
                question_id = self.question.get('id')
                if question_id in ['swap_exact_tokens_for_tokens', 'swap_tokens_for_exact_tokens']:
                    # Token to Token: track both input and output tokens
                    token_address = self.generated_params.get('token_in_address')
                    token_out_address = self.generated_params.get('token_out_address')
                    spender_address = self.generated_params.get('router_address')
                elif question_id == 'swap_multihop_routing':
                    # Multi-hop routing: track start and end tokens
                    token_address = self.generated_params.get('token_start_address')
                    token_out_address = self.generated_params.get('token_end_address')
                    spender_address = self.generated_params.get('router_address')
                elif question_id == 'swap_exact_tokens_for_bnb':
                    # Token to BNB: track input token
                    token_address = self.generated_params.get('token_address')
                    spender_address = self.generated_params.get('router_address')
                else:
                    # BNB to Token: track output token
                    token_address = self.generated_params.get('token_address')
                    spender_address = self.generated_params.get('router_address')
            elif self.question.get('subcategory') == 'pancakeswap_liquidity':
                # PancakeSwap liquidity operations need to track token balance, allowance, and LP tokens
                question_id = self.question.get('id')
                if question_id == 'add_liquidity_bnb_token':
                    # Add BNB + Token liquidity: track token and LP token
                    token_address = self.generated_params.get('token_address')
                    spender_address = self.generated_params.get('router_address')
                    # Get LP token address (needs env, so get it here after env is created)
                    lp_token_address = self._get_lp_token_address(
                        env,
                        '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',  # WBNB
                        token_address
                    )
                elif question_id == 'add_liquidity_tokens':
                    # Add Token + Token liquidity: track both tokens and LP token
                    token_address = self.generated_params.get('token_a_address')
                    token_out_address = self.generated_params.get('token_b_address')
                    spender_address = self.generated_params.get('router_address')
                    # Get LP token address for the token pair
                    lp_token_address = self._get_lp_token_address(
                        env,
                        token_address,
                        token_out_address
                    )
                elif question_id == 'remove_liquidity_tokens':
                    # Remove Token + Token liquidity: track both tokens and LP token
                    # For removal, we need to track LP token (which will decrease) and both tokens (which will increase)
                    token_address = self.generated_params.get('token_a_address')
                    token_out_address = self.generated_params.get('token_b_address')
                    spender_address = self.generated_params.get('router_address')  # LP token needs to be approved for Router
                    # Get LP token address for the token pair
                    lp_token_address = self._get_lp_token_address(
                        env,
                        token_address,
                        token_out_address
                    )
                elif question_id == 'remove_liquidity_bnb_token':
                    # Remove BNB + Token liquidity: track token and LP token
                    # For removal, we need to track LP token (which will decrease) and token (which will increase)
                    # BNB balance will also increase
                    token_address = self.generated_params.get('token_address')
                    spender_address = self.generated_params.get('router_address')  # LP token needs to be approved for Router
                    # Get LP token address for WBNB/Token pair
                    lp_token_address = self._get_lp_token_address(
                        env,
                        '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',  # WBNB
                        token_address
                    )
            elif self.question.get('id') in ['wbnb_deposit', 'wbnb_withdraw']:
                # WBNB deposit/withdraw needs to query WBNB token balance
                token_address = self.generated_params.get('wbnb_address')
            elif self.question.get('subcategory') == 'flashloan':
                # Flashloan needs to query token balance (for fee payment verification)
                token_address = self.generated_params.get('token_address')
            elif self.question.get('subcategory') == 'staking_farming':
                # Staking/Farming operations need to track token balance, allowance, and staked amount
                question_id = self.question.get('id')
                if question_id == 'stake_single_token':
                    # CAKE token staking
                    token_address = self.generated_params.get('token_address')  # CAKE token
                    spender_address = self.generated_params.get('pool_address')  # SimpleStaking
                    pool_address = self.generated_params.get('pool_address')
                elif question_id == 'stake_lp_tokens':
                    # LP token staking
                    lp_token_address = self.generated_params.get('lp_token_address')  # USDT/BUSD LP
                    spender_address = self.generated_params.get('pool_address')  # SimpleLPStaking
                    pool_address = self.generated_params.get('pool_address')
                elif question_id == 'unstake_lp_tokens':
                    # Unstake LP tokens - track LP token balance and staked amount
                    lp_token_address = self.generated_params.get('lp_token_address')  # USDT/BUSD LP
                    pool_address = self.generated_params.get('pool_address')  # SimpleRewardPool
                elif question_id == 'harvest_rewards':
                    # Harvest rewards - track CAKE token balance
                    token_address = self.generated_params.get('reward_token_address')  # CAKE token
                    pool_address = self.generated_params.get('pool_address')  # SimpleRewardPool
                elif question_id == 'unstake_and_harvest':
                    # Unstake and harvest - track LP tokens, CAKE rewards, and staked amount
                    lp_token_address = self.generated_params.get('lp_token_address')  # USDT/BUSD LP
                    token_address = self.generated_params.get('reward_token_address')  # CAKE token
                    pool_address = self.generated_params.get('pool_address')  # SimpleRewardPool
                elif question_id == 'emergency_withdraw':
                    # Emergency withdraw - track LP tokens (returned), CAKE (should not change), staked amount (should become 0)
                    lp_token_address = self.generated_params.get('lp_token_address')  # USDT/BUSD LP
                    token_address = self.generated_params.get('reward_token_address')  # CAKE token (for verification that it doesn't increase)
                    pool_address = self.generated_params.get('pool_address')  # SimpleRewardPool
            elif self.question.get('id') == 'contract_call_simple':
                # SimpleCounter contract needs to query counter value
                counter_contract_address = self.generated_params.get('contract_address')
            elif self.question.get('id') == 'contract_call_with_params':
                # MessageBoard contract needs to query message value
                message_board_contract_address = self.generated_params.get('contract_address')
            elif self.question.get('subcategory') == 'delegate_call':
                # DelegateCall needs to query proxy and implementation values
                proxy_address = self.generated_params.get('proxy_address')
                implementation_address = self.generated_params.get('implementation_address')
                expected_value = self.generated_params.get('value')
            elif self.question.get('subcategory') == 'nft_operations':
                # NFT operations need to query NFT ownership
                nft_address = self.generated_params.get('nft_address')
                nft_token_id = self.generated_params.get('token_id')
                operator_address = self.generated_params.get('operator_address')
                
                # Determine NFT type based on question ID
                question_id = self.question.get('id', '')
                if 'erc1155' in question_id:
                    nft_type = 'erc1155'
                    # ERC1155 transfer operation also needs to query target address balance
                    target_address_for_token = self.generated_params.get('to_address')
                elif 'erc721' in question_id:
                    nft_type = 'erc721'
                else:
                    nft_type = None
            
            # Execute transaction
            # Get requires_contract from metadata
            requires_contract = self.question.get('metadata', {}).get('requires_contract', False)
            
            execution_result = executor.execute_transaction(
                tx,
                validator,
                token_address=token_address,
                target_address_for_token=target_address_for_token,
                token_out_address=token_out_address,
                spender_address=spender_address,
                lp_token_address=lp_token_address,
                pool_address=pool_address,
                nft_address=nft_address,
                nft_token_id=nft_token_id,
                operator_address=operator_address,
                nft_type=nft_type,
                counter_contract_address=counter_contract_address,
                message_board_contract_address=message_board_contract_address,
                proxy_address=proxy_address,
                implementation_address=implementation_address,
                expected_value=expected_value,
                from_address=from_address,
                requires_contract=requires_contract
            )
            
            self.result['execution_success'] = execution_result['success']
            
            if execution_result['success']:
                self.result['validation_result'] = execution_result['validation']
                print()
                print("="*80)
                print("📊 Evaluation Result")
                print("="*80)
                print(f"✅ Transaction executed successfully")
                print(f"Validation Passed: {'✅' if execution_result['validation']['passed'] else '❌'}")
                print(f"Score: {execution_result['validation']['score']}/{execution_result['validation']['max_score']}")
                print("="*80)
            else:
                error_msg = execution_result.get('error', 'Unknown error')
                print(f"❌ Transaction execution failed: {error_msg}")
                self.result['error'] = error_msg
            
        finally:
            # Cleanup environment (only stop if newly started)
            if should_stop_env:
                print("\n🧹 Cleaning up environment...")
                env.stop()
            else:
                print("\n✓ Environment reused, keeping running")
        
        self.result['end_time'] = datetime.now().isoformat()
        return self.result
    
    def _setup_query_operation(self, env, params: Dict[str, Any]):
        """
        Setup for query operations - set random balance/allowance for query
        
        Args:
            env: QuestEnvironment instance
            params: Generated parameters including addresses and expected values
        """
        from decimal import Decimal
        from eth_utils import to_checksum_address
        
        question_id = self.question.get('id')
        
        # Get expected value based on question type
        expected_value = params.get('expected_balance') or params.get('expected_allowance')
        expected_approved_address = params.get('expected_approved_address')
        
        # Skip if no expected values (but continue for NFT approval)
        if expected_value is None and expected_approved_address is None:
            return
        
        print(f"\n🔧 Setting up query operation: {question_id}")
        if expected_value is not None:
            print(f"   Expected value: {expected_value}")
        if expected_approved_address is not None:
            print(f"   Expected approved address: {expected_approved_address}")
        
        try:
            if question_id == 'query_bnb_balance':
                # Set BNB balance using anvil_setBalance
                query_address = params.get('query_address')
                if not query_address:
                    return
                query_address = to_checksum_address(query_address)
                print(f"   Query address: {query_address}")
                
                balance_wei = int(Decimal(str(expected_value)) * Decimal(10**18))
                env.w3.provider.make_request(
                    'anvil_setBalance',
                    [query_address, hex(balance_wei)]
                )
                
                # Verify
                actual_balance = env.w3.eth.get_balance(query_address)
                print(f"   ✅ BNB balance set: {actual_balance / 10**18:.6f} BNB")
                
            elif question_id == 'query_erc20_balance':
                # Set ERC20 token balance using anvil_setStorageAt
                query_address = params.get('query_address')
                token_address = params.get('token_address')
                token_decimals = params.get('token_decimals', 18)
                
                if query_address and token_address:
                    query_address = to_checksum_address(query_address)
                    print(f"   Query address: {query_address}")
                    
                    balance_raw = int(Decimal(str(expected_value)) * Decimal(10**token_decimals))
                    
                    # Use environment's _set_erc20_balance_direct method
                    # ERC1363 test token uses balance slot 4
                    success = env._set_erc20_balance_direct(
                        token_address,
                        query_address,
                        balance_raw,
                        balance_slot=4
                    )
                    
                    if success:
                        print(f"   ✅ Token balance set: {expected_value} tokens")
                    else:
                        print(f"   ⚠️  Warning: Failed to set token balance")
                else:
                    print(f"   ⚠️  Warning: Missing parameters for balance setup")
            
            elif question_id == 'query_erc20_allowance':
                # Set ERC20 token allowance using anvil_setStorageAt
                token_address = params.get('token_address')
                owner_address = params.get('owner_address')
                spender_address = params.get('spender_address')
                token_decimals = params.get('token_decimals', 18)
                
                if token_address and owner_address and spender_address:
                    print(f"   Owner: {owner_address}")
                    print(f"   Spender: {spender_address}")
                    
                    allowance_raw = int(Decimal(str(expected_value)) * Decimal(10**token_decimals))
                    
                    # Set allowance via contract call (more reliable than storage manipulation)
                    # Use impersonation to call approve() from owner's account
                    success = self._set_erc20_allowance_via_approve(
                        env,
                        token_address,
                        owner_address,
                        spender_address,
                        allowance_raw
                    )
                    
                    if success:
                        print(f"   ✅ Token allowance set: {expected_value} tokens")
                    else:
                        print(f"   ⚠️  Warning: Failed to set token allowance")
                else:
                    print(f"   ⚠️  Warning: Missing parameters for allowance setup")
            
            elif question_id == 'query_nft_approval_status':
                # Set NFT approval using approve() function
                nft_address = params.get('nft_address')
                token_id = params.get('token_id')
                approved_address = params.get('expected_approved_address')
                
                if nft_address and token_id is not None and approved_address:
                    print(f"   NFT: {nft_address}")
                    print(f"   Token ID: {token_id}")
                    print(f"   Approved address: {approved_address}")
                    
                    # Set approval via contract call using impersonation
                    success = self._set_nft_approval_via_approve(
                        env,
                        nft_address,
                        token_id,
                        approved_address
                    )
                    
                    if success:
                        print(f"   ✅ NFT approval set for token #{token_id}")
                    else:
                        print(f"   ⚠️  Warning: Failed to set NFT approval")
                else:
                    print(f"   ⚠️  Warning: Missing parameters for NFT approval setup")
        
        except Exception as e:
            print(f"   ⚠️  Warning: Failed to setup query operation: {e}")
            import traceback
            traceback.print_exc()
    
    def _set_erc20_allowance_via_approve(
        self,
        env,
        token_address: str,
        owner_address: str,
        spender_address: str,
        amount: int
    ) -> bool:
        """
        Set ERC20 allowance via approve() function using account impersonation
        
        Args:
            env: QuestEnvironment instance
            token_address: Token contract address
            owner_address: Owner address (will be impersonated)
            spender_address: Spender address
            amount: Allowance amount in smallest unit
            
        Returns:
            bool: True if successful
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        
        try:
            token_address = to_checksum_address(token_address)
            owner_address = to_checksum_address(owner_address)
            spender_address = to_checksum_address(spender_address)
            
            print(f"    [DEBUG] Token: {token_address}")
            print(f"    [DEBUG] Owner: {owner_address}")
            print(f"    [DEBUG] Spender: {spender_address}")
            print(f"    [DEBUG] Amount: {amount}")
            
            # Give owner some BNB for gas fees
            print(f"    [DEBUG] Setting owner balance for gas...")
            env.w3.provider.make_request('anvil_setBalance', [owner_address, hex(10**18)])  # 1 BNB
            
            # Impersonate owner account
            print(f"    [DEBUG] Impersonating owner...")
            env.w3.provider.make_request('anvil_impersonateAccount', [owner_address])
            
            # ERC20 approve function selector: 0x095ea7b3
            # approve(address spender, uint256 amount)
            approve_selector = bytes.fromhex('095ea7b3')
            approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [spender_address, amount]).hex()
            
            print(f"    [DEBUG] Calling approve()...")
            # Send approve transaction
            response = env.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': owner_address,
                    'to': token_address,
                    'data': approve_data,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)
                }]
            )
            
            # Check response
            if 'result' not in response:
                print(f"    [DEBUG] Approve transaction failed: {response.get('error', 'Unknown error')}")
                return False
            
            tx_hash = response['result']
            print(f"    [DEBUG] Approve tx hash: {tx_hash}")
            
            # Wait for confirmation
            max_attempts = 20
            for i in range(max_attempts):
                receipt = env.w3.eth.get_transaction_receipt(tx_hash)
                if receipt is not None:
                    if receipt['status'] == 1:
                        print(f"    [DEBUG] Approve transaction confirmed")
                        break
                    else:
                        print(f"    [DEBUG] Approve transaction failed (status=0)")
                        return False
                time.sleep(0.1)
            else:
                print(f"    [DEBUG] Approve transaction not confirmed after {max_attempts} attempts")
                return False
            
            # Stop impersonating
            env.w3.provider.make_request('anvil_stopImpersonatingAccount', [owner_address])
            
            # Verify allowance
            print(f"    [DEBUG] Verifying allowance...")
            token_contract = env.w3.eth.contract(
                address=token_address,
                abi=[{
                    "constant": True,
                    "inputs": [
                        {"name": "owner", "type": "address"},
                        {"name": "spender", "type": "address"}
                    ],
                    "name": "allowance",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "type": "function"
                }]
            )
            
            actual_allowance = token_contract.functions.allowance(owner_address, spender_address).call()
            print(f"    [DEBUG] Actual allowance after setting: {actual_allowance}")
            print(f"    [DEBUG] Expected: {amount}")
            print(f"    [DEBUG] Match: {actual_allowance == amount}")
            
            return actual_allowance == amount
            
        except Exception as e:
            print(f"    [DEBUG] Error setting allowance: {e}")
            import traceback
            traceback.print_exc()
            # Stop impersonating in case of error
            try:
                env.w3.provider.make_request('anvil_stopImpersonatingAccount', [owner_address])
            except:
                pass
            return False
    
    def _set_nft_approval_via_approve(
        self,
        env,
        nft_address: str,
        token_id: int,
        approved_address: str
    ) -> bool:
        """
        Set NFT approval via approve() function using account impersonation
        
        Args:
            env: QuestEnvironment instance
            nft_address: NFT contract address
            token_id: Token ID to approve
            approved_address: Address to approve
            
        Returns:
            bool: True if successful
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        
        try:
            nft_address = to_checksum_address(nft_address)
            approved_address = to_checksum_address(approved_address)
            
            print(f"    [DEBUG] NFT: {nft_address}")
            print(f"    [DEBUG] Token ID: {token_id}")
            print(f"    [DEBUG] Approved address: {approved_address}")
            
            # Get the current owner of the token
            # ERC721 ownerOf function selector: 0x6352211e
            owner_selector = bytes.fromhex('6352211e')
            owner_data = '0x' + owner_selector.hex() + encode(['uint256'], [token_id]).hex()
            
            owner_result = env.w3.eth.call({
                'to': nft_address,
                'data': owner_data
            })
            owner_address = '0x' + owner_result.hex()[-40:]  # Extract address from result
            owner_address = to_checksum_address(owner_address)
            print(f"    [DEBUG] Token owner: {owner_address}")
            
            # Give owner some BNB for gas fees
            print(f"    [DEBUG] Setting owner balance for gas...")
            env.w3.provider.make_request('anvil_setBalance', [owner_address, hex(10**18)])  # 1 BNB
            
            # Impersonate owner account
            print(f"    [DEBUG] Impersonating owner...")
            env.w3.provider.make_request('anvil_impersonateAccount', [owner_address])
            
            # ERC721 approve function selector: 0x095ea7b3
            # approve(address to, uint256 tokenId)
            approve_selector = bytes.fromhex('095ea7b3')
            approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [approved_address, token_id]).hex()
            
            print(f"    [DEBUG] Calling approve()...")
            # Send approve transaction
            response = env.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': owner_address,
                    'to': nft_address,
                    'data': approve_data,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)
                }]
            )
            
            # Check response
            if 'result' not in response:
                print(f"    [DEBUG] Approve transaction failed: {response.get('error', 'Unknown error')}")
                return False
            
            tx_hash = response['result']
            print(f"    [DEBUG] Approve tx hash: {tx_hash}")
            
            # Wait for confirmation
            max_attempts = 20
            for i in range(max_attempts):
                receipt = env.w3.eth.get_transaction_receipt(tx_hash)
                if receipt is not None:
                    if receipt['status'] == 1:
                        print(f"    [DEBUG] Approve transaction confirmed")
                        break
                    else:
                        print(f"    [DEBUG] Approve transaction failed (status=0)")
                        return False
                time.sleep(0.1)
            else:
                print(f"    [DEBUG] Approve transaction not confirmed after {max_attempts} attempts")
                return False
            
            # Stop impersonating
            env.w3.provider.make_request('anvil_stopImpersonatingAccount', [owner_address])
            
            # Verify approval
            print(f"    [DEBUG] Verifying approval...")
            # getApproved(uint256 tokenId) selector: 0x081812fc
            get_approved_data = '0x081812fc' + encode(['uint256'], [token_id]).hex()
            result = env.w3.eth.call({
                'to': nft_address,
                'data': get_approved_data
            })
            actual_approved = '0x' + result.hex()[-40:]
            actual_approved = to_checksum_address(actual_approved)
            print(f"    [DEBUG] Actual approved address after setting: {actual_approved}")
            print(f"    [DEBUG] Expected: {approved_address}")
            print(f"    [DEBUG] Match: {actual_approved.lower() == approved_address.lower()}")
            
            return actual_approved.lower() == approved_address.lower()
            
        except Exception as e:
            print(f"    [DEBUG] Error setting NFT approval: {e}")
            import traceback
            traceback.print_exc()
            # Stop impersonating in case of error
            try:
                env.w3.provider.make_request('anvil_stopImpersonatingAccount', [owner_address])
            except:
                pass
            return False
    
    def _create_validator(self, params: Dict[str, Any]):
        """
        Create validator instance
        
        Args:
            params: Generated parameters for this test case
            
        Returns:
            Validator instance
        """
        # validator_class should be a factory function
        # It accepts params and returns a validator instance
        if callable(self.validator_class):
            return self.validator_class(**params)
        else:
            raise ValueError("validator_class must be callable")
    
    async def run_multi_turn(self) -> Dict[str, Any]:
        """
        Run multi-turn evaluation (for composite problems)
        
        LLM can:
        1. Plan tasks
        2. Execute subtasks step by step
        3. Query chain state
        4. Detect errors and report
        5. Submit when complete (submit: true)
        
        Returns:
            Evaluation result dictionary
        """
        print("="*80)
        print("BSC Quest Bench - Multi-Turn Evaluation (Composite Problem)")
        print("="*80)
        print(f"Question ID: {self.question['id']}")
        print(f"Model: {self.model_name}")
        print(f"Difficulty: {self.question['difficulty']}")
        
        # Get interaction config
        interaction_config = self.question.get('composite_structure', {}).get('interaction_config', {})
        optimal_steps = interaction_config.get('optimal_steps', 3)
        max_rounds_multiplier = interaction_config.get('max_rounds_multiplier', 2)
        max_rounds = optimal_steps * max_rounds_multiplier
        
        print(f"Optimal Steps: {optimal_steps}")
        print(f"Max Rounds: {max_rounds} ({optimal_steps} × {max_rounds_multiplier})")
        print("="*80)
        print()
        
        self.result['start_time'] = datetime.now().isoformat()
        self.result['interaction_history'] = []
        self.result['total_rounds'] = 0
        self.result['optimal_steps'] = optimal_steps
        self.result['max_rounds'] = max_rounds
        
        # 1. Start environment
        should_stop_env = False
        if self.reuse_env:
            print("🔧 Reusing existing environment...")
            env = self.reuse_env
            env_info = self._get_env_info(env)
            print()
        else:
            print("🔧 Starting new environment...")
            env = QuestEnvironment(fork_url=self.fork_url)
            env_info = env.start()
            should_stop_env = True
        
        # Regenerate environment-dependent parameters
        self._regenerate_env_parameters(env)
        
        try:
            # 2. Display generated parameters
            print("📝 Generated Natural Language Prompt:")
            system_prompt = self._generate_system_prompt()
            print(f"   \"{self.result['natural_language_prompt']}\"")
            
            print(f"\n📊 Generated Parameters:")
            for param_name, param_value in self.generated_params.items():
                print(f"   - {param_name}: {param_value}")
            print()
            
            # 3. Add multi-turn specific instructions to system prompt
            multi_turn_instructions = f"""

MULTI-TURN INTERACTION RULES:
- You have a MAXIMUM of {max_rounds} rounds to complete this task
- The OPTIMAL solution requires {optimal_steps} steps
- Your score will be: base_score × (optimal_steps / actual_steps) = base_score × ({optimal_steps} / your_steps)
- IMPORTANT: Complete the task in as few steps as possible to maximize your score
- When you finish or detect an error, ALWAYS set "submit": true to end the session
- If you reach round {max_rounds} without submitting, the system will force submission

Example response formats:
1. To query: {{"action": "query", "query_type": "token_balance", "token_address": "0x...", "submit": false}}
2. To execute: Return TypeScript code block
3. To submit completion: {{"action": "complete", "submit": true}}
4. To report error: {{"error_detected": true, "error_type": "TOKEN_INSUFFICIENT_BALANCE", "error_message": "...", "submit": true}}
"""
            system_prompt = system_prompt + multi_turn_instructions
            
            # 3. Initialize conversation
            messages = [SystemMessage(content=system_prompt)]
            
            # 4. Multi-turn interaction loop
            final_submission = None
            
            for round_num in range(1, max_rounds + 1):
                print(f"\n{'='*80}")
                print(f"🔄 Round {round_num}/{max_rounds}")
                print(f"{'='*80}\n")
                
                # Call LLM
                print(f"🤖 Calling LLM (Round {round_num})...")
                response = await self.llm.ainvoke(messages)
                response_content = response.content
                
                print(f"✅ LLM response received ({len(response_content)} characters)\n")
                
                # Store in history
                round_data = {
                    'round': round_num,
                    'llm_response': response_content,
                    'timestamp': datetime.now().isoformat()
                }
                
                # Parse response
                # LLM should return JSON with action/error_detected/submit fields
                parsed_response = self._parse_llm_response(response_content)
                round_data['parsed_response'] = parsed_response
                
                print(f"📋 Parsed Response:")
                print(f"   Action: {parsed_response.get('action', 'execute')}")
                print(f"   Submit: {parsed_response.get('submit', False)}")
                print(f"   Error Detected: {parsed_response.get('error_detected', False)}")
                print()
                
                # Check if LLM wants to submit (without any action)
                if parsed_response.get('submit') and parsed_response.get('action') not in ['execute', 'query']:
                    print("✅ LLM submitted the task (no action)\n")
                    final_submission = parsed_response
                    self.result['interaction_history'].append(round_data)
                    self.result['total_rounds'] = round_num
                    break
                
                # Execute the action
                action_result = await self._execute_action(
                    parsed_response, 
                    env, 
                    env_info
                )
                
                round_data['action_result'] = action_result
                self.result['interaction_history'].append(round_data)
                
                # Check if this was the final action (submit after execute)
                if parsed_response.get('submit'):
                    print("✅ LLM submitted after executing action\n")
                    final_submission = parsed_response
                    final_submission['final_action_result'] = action_result
                    self.result['total_rounds'] = round_num
                    break
                
                # Add result to conversation
                result_message = self._format_action_result(action_result)
                messages.append(AIMessage(content=response_content))
                messages.append(HumanMessage(content=result_message))
                
                print(f"📤 Sent result back to LLM\n")
            
            else:
                # Max rounds reached - force submission and validate
                print(f"⚠️  Max rounds ({max_rounds}) reached without explicit submission")
                print(f"   Forcing submission and validating final state...\n")
                self.result['total_rounds'] = max_rounds
                
                # Force submission with whatever we have
                final_submission = {
                    'submit': True,
                    'forced': True,
                    'error_detected': False
                }
            
            # 5. Validation
            if final_submission:
                print("\n" + "="*80)
                print("🔍 Validating final submission...")
                print("="*80 + "\n")
                
                # Create validator
                validator = self._create_validator(self.generated_params)
                
                # Get final chain state
                final_state = self._get_final_chain_state(env, env_info)
                
                # Validate
                validation_result = validator.validate(
                    final_submission=final_submission,
                    chain_state=final_state,
                    task_params=self.generated_params,
                    interaction_history=self.result['interaction_history']
                )
                
                # Apply step-based score decay
                base_score = validation_result.get('score', 0)
                actual_steps = self.result['total_rounds']
                
                # Calculate decay factor
                decay_factor = min(1.0, optimal_steps / actual_steps) if actual_steps > 0 else 0
                final_score = base_score * decay_factor
                
                print(f"\n📉 Step-Based Score Adjustment:")
                print(f"   Base Score: {base_score:.2f}")
                print(f"   Optimal Steps: {optimal_steps}")
                print(f"   Actual Steps: {actual_steps}")
                print(f"   Decay Factor: {decay_factor:.3f} ({optimal_steps}/{actual_steps})")
                print(f"   Final Score: {final_score:.2f}")
                
                # Update validation result with decayed score
                validation_result['base_score'] = base_score
                validation_result['decay_factor'] = decay_factor
                validation_result['optimal_steps'] = optimal_steps
                validation_result['actual_steps'] = actual_steps
                validation_result['score'] = final_score
                validation_result['passed'] = final_score >= 60.0
                
                self.result['execution_success'] = True
                self.result['validation_result'] = validation_result
                self.result['final_submission'] = final_submission
                
                print()
                print("="*80)
                print("📊 Evaluation Result")
                print("="*80)
                print(f"Validation Passed: {'✅' if validation_result.get('passed') else '❌'}")
                print(f"Base Score: {validation_result.get('base_score', 0):.2f}/{validation_result.get('max_score', 100)}")
                print(f"Final Score: {validation_result.get('score', 0):.2f}/{validation_result.get('max_score', 100)} (after {decay_factor:.1%} decay)")
                print(f"Steps: {actual_steps} used (optimal: {optimal_steps})")
                print(f"Status: {validation_result.get('status', 'unknown')}")
                print("="*80)
            
        except Exception as e:
            print(f"\n❌ Error during multi-turn evaluation: {e}")
            import traceback
            traceback.print_exc()
            self.result['error'] = str(e)
            self.result['execution_success'] = False
            
        finally:
            # Cleanup
            if should_stop_env:
                print("\n🧹 Cleaning up environment...")
                env.stop()
                print("✓ Anvil process terminated")
                print("✓ Environment cleaned up")
        
        self.result['end_time'] = datetime.now().isoformat()
        return self.result
    
    def _get_env_info(self, env) -> Dict[str, Any]:
        """Get environment info from existing environment"""
        return {
            'rpc_url': f'http://127.0.0.1:{env.anvil_port}',
            'chain_id': env.chain_id,
            'test_address': env.test_address,
            'test_private_key': env.test_account.key.hex(),
            'simple_staking_address': getattr(env, 'simple_staking_address', None),
            'simple_lp_staking_address': getattr(env, 'simple_lp_staking_address', None),
            'simple_reward_pool_address': getattr(env, 'simple_reward_pool_address', None),
            'erc1363_token_address': getattr(env, 'erc1363_token_address', None),
            'erc1155_token_address': getattr(env, 'erc1155_token_address', None),
            'flashloan_contract_address': getattr(env, 'flashloan_contract_address', None),
            'simple_counter_address': getattr(env, 'simple_counter_address', None),
            'donation_box_address': getattr(env, 'donation_box_address', None),
            'message_board_address': getattr(env, 'message_board_address', None),
            'proxy_address': getattr(env, 'proxy_address', None),
            'implementation_address': getattr(env, 'implementation_address', None),
            'fallback_receiver_address': getattr(env, 'fallback_receiver_address', None),
            'rich_address': getattr(env, 'rich_address', None),
            'erc721_test_nft_address': getattr(env, 'erc721_test_nft_address', None),
        }
    
    def _parse_llm_response(self, response_content: str) -> Dict[str, Any]:
        """Parse LLM response to extract action/error/submit fields"""
        import re
        
        # PRIORITY 1: Check for TypeScript code block FIRST (most important for execution)
        has_code = '```typescript' in response_content or '```ts' in response_content
        has_submit = 'submit' in response_content.lower() and 'true' in response_content.lower()
        
        if has_code:
            print(f"   [DEBUG] Detected TypeScript code block")
            # Check if this is the final submission with code
            if has_submit:
                print(f"   [DEBUG] Detected submit=true WITH code - will execute then submit")
                return {
                    'action': 'execute',
                    'code': response_content,
                    'submit': True,  # Mark as final submission
                    'error_detected': False
                }
            else:
                return {
                    'action': 'execute',
                    'code': response_content,
                    'submit': False,
                    'error_detected': False
                }
        
        # PRIORITY 2: Look for JSON code block (for queries and error reports)
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                print(f"   [DEBUG] Parsed from ```json block: {parsed}")
                return parsed
            except Exception as e:
                print(f"   [DEBUG] Failed to parse ```json block: {e}")
        
        # PRIORITY 3: Look for raw JSON object
        json_patterns = [
            r'\{[^{}]*?"submit"\s*:\s*true[^{}]*?\}',  # Find any JSON with submit: true
            r'\{[^{}]*?"error_detected"\s*:\s*true[^{}]*?\}',  # Find any JSON with error_detected: true
            r'\{[^{}]*?"action"\s*:\s*"[^"]*?"[^{}]*?\}',  # Find any JSON with action field
        ]
        
        for pattern in json_patterns:
            json_match = re.search(pattern, response_content, re.DOTALL | re.IGNORECASE)
            if json_match:
                try:
                    json_str = json_match.group(0)
                    parsed = json.loads(json_str)
                    print(f"   [DEBUG] Parsed from pattern {pattern[:30]}...: {parsed}")
                    return parsed
                except Exception as e:
                    print(f"   [DEBUG] Failed to parse with pattern: {e}")
                    continue
        
        # PRIORITY 4: Check for submit keyword only
        response_lower = response_content.lower()
        if 'submit' in response_lower and 'true' in response_lower:
            print(f"   [DEBUG] Detected 'submit: true' in text")
            return {
                'action': 'submit',
                'submit': True,
                'error_detected': 'error' in response_lower
            }
        
        # Default: assume it's code execution
        print(f"   [DEBUG] Defaulting to execute action")
        return {
            'action': 'execute',
            'code': response_content,
            'submit': False,
            'error_detected': False
        }
    
    async def _execute_action(self, parsed_response: Dict[str, Any], env, env_info: Dict[str, Any]) -> Dict[str, Any]:
        """Execute LLM's requested action"""
        action = parsed_response.get('action', 'execute')
        
        if action == 'query':
            # Query chain state
            return self._handle_query_action(parsed_response, env, env_info)
        elif action == 'execute':
            # Execute transaction
            return await self._handle_execute_action(parsed_response, env, env_info)
        else:
            return {'success': False, 'error': f'Unknown action: {action}'}
    
    def _handle_query_action(self, parsed_response: Dict[str, Any], env, env_info: Dict[str, Any]) -> Dict[str, Any]:
        """Handle query action (e.g., check balance)"""
        query_type = parsed_response.get('query_type', 'balance')
        
        if query_type == 'balance' or query_type == 'token_balance':
            token_address = parsed_response.get('token_address')
            account_address = parsed_response.get('account_address', env_info['test_address'])
            
            if not token_address:
                return {'success': False, 'error': 'token_address required for balance query'}
            
            try:
                from eth_utils import to_checksum_address
                token_addr = to_checksum_address(token_address)
                account_addr = to_checksum_address(account_address)
                
                # Query ERC20 balance
                data = '0x70a08231' + '000000000000000000000000' + account_addr[2:]
                result = env.w3.eth.call({
                    'to': token_addr,
                    'data': data
                })
                balance = int(result.hex(), 16)
                balance_ether = balance / (10**18)
                
                return {
                    'success': True,
                    'query_type': 'token_balance',
                    'token_address': token_address,
                    'account_address': account_address,
                    'balance_wei': balance,
                    'balance_tokens': balance_ether
                }
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        return {'success': False, 'error': f'Unknown query type: {query_type}'}
    
    async def _handle_execute_action(self, parsed_response: Dict[str, Any], env, env_info: Dict[str, Any]) -> Dict[str, Any]:
        """Handle execute action (execute transaction)"""
        # Extract code from response
        code = parsed_response.get('code', '')
        
        # Extract TypeScript code block
        code_blocks = self.extract_code_blocks(code)
        if not code_blocks:
            return {'success': False, 'error': 'No code block found'}
        
        code = code_blocks[0]
        
        # Execute code
        from .skill_manager.ts_skill_manager import TypeScriptSkillManager
        
        skill_manager = TypeScriptSkillManager(use_bun=True)
        code_file = self._save_code_to_temp_file(code)
        
        try:
            deployed_contracts = {
                'simple_staking': env_info.get('simple_staking_address'),
                'simple_lp_staking': env_info.get('simple_lp_staking_address'),
                'simple_reward_pool': env_info.get('simple_reward_pool_address'),
                'erc1363_token': env_info.get('erc1363_token_address'),
                'erc1155_token': env_info.get('erc1155_token_address'),
                'flashloan_contract': env_info.get('flashloan_contract_address'),
                'simple_counter': env_info.get('simple_counter_address'),
                'donation_box': env_info.get('donation_box_address'),
                'message_board': env_info.get('message_board_address'),
                'proxy': env_info.get('proxy_address'),
                'implementation': env_info.get('implementation_address'),
                'fallback_receiver': env_info.get('fallback_receiver_address'),
                'rich_address': env_info.get('rich_address')
            }
            deployed_contracts = {k: v for k, v in deployed_contracts.items() if v is not None}
            
            tx_result = skill_manager.execute_skill(
                code_file=code_file,
                provider_url=env_info['rpc_url'],
                agent_address=env_info['test_address'],
                deployed_contracts=deployed_contracts
            )
            
            if not tx_result.get('success'):
                return {
                    'success': False,
                    'error': tx_result.get('error', 'Execution failed')
                }
            
            # Execute transaction
            tx = tx_result['tx_object']
            executor = QuestExecutor(
                w3=env.w3,
                private_key=env_info['test_private_key']
            )
            
            # Prepare transaction
            from eth_utils import to_checksum_address
            chain_id = env.w3.eth.chain_id
            
            transaction = {
                'from': to_checksum_address(env_info['test_address']),
                'to': to_checksum_address(tx['to']) if tx.get('to') else None,
                'value': int(tx.get('value', 0)),
                'gas': int(tx.get('gasLimit', tx.get('gas', 500000))),
                'nonce': env.w3.eth.get_transaction_count(env_info['test_address']),
                'chainId': chain_id,
            }
            
            # Handle gas price
            tx_type = tx.get('type', 0)
            if tx_type == 2:
                transaction['maxPriorityFeePerGas'] = int(tx.get('maxPriorityFeePerGas', 10**9))
                transaction['maxFeePerGas'] = int(tx.get('maxFeePerGas', 2 * 10**9))
                transaction['type'] = 2
            else:
                transaction['gasPrice'] = int(tx.get('gasPrice', 10**9))
            
            if 'data' in tx and tx['data']:
                transaction['data'] = tx['data']
            
            # Sign and send
            signed_tx = env.w3.eth.account.sign_transaction(transaction, env_info['test_private_key'])
            tx_hash = env.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # Wait for receipt
            receipt = env.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            return {
                'success': True,
                'tx_hash': tx_hash.hex(),
                'block_number': receipt['blockNumber'],
                'gas_used': receipt['gasUsed'],
                'status': receipt['status']
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
        finally:
            import os
            if os.path.exists(code_file):
                os.unlink(code_file)
    
    def _format_action_result(self, action_result: Dict[str, Any]) -> str:
        """Format action result as message for LLM"""
        if not action_result.get('success'):
            return f"Action failed: {action_result.get('error')}"
        
        if 'balance_tokens' in action_result:
            # Query result
            return f"Query result: Balance = {action_result['balance_tokens']} tokens ({action_result['balance_wei']} wei)"
        elif 'tx_hash' in action_result:
            # Transaction result
            return f"Transaction executed successfully. Hash: {action_result['tx_hash']}, Block: {action_result['block_number']}, Gas: {action_result['gas_used']}, Status: {action_result['status']}"
        else:
            return f"Action completed: {json.dumps(action_result)}"
    
    def _get_final_chain_state(self, env, env_info: Dict[str, Any]) -> Dict[str, Any]:
        """Get final chain state for validation"""
        # TODO: Implement comprehensive state collection
        return {
            'block_number': env.w3.eth.block_number,
            'agent_address': env_info['test_address'],
            'agent_balance': env.w3.eth.get_balance(env_info['test_address'])
        }
    
    def save_result(self, output_path: str):
        """
        Save results to file
        
        Args:
            output_path: Output file path
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.result, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Results saved to: {output_path}")

