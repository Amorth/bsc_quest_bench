"""
BSC Quest Controller - 控制层

负责:
1. 管理 LLM 输入输出
2. 协调各层交互 (环境层、执行层、验证器)
3. 提取 TypeScript 代码块
4. 保存评分指标
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

from .quest_env import QuestEnvironment
from .quest_executor import QuestExecutor
from .parameter_generator import ParameterGenerator, format_parameter_value


class QuestController:
    """Quest 控制器 - 协调单轮交易生成评估"""
    
    def __init__(
        self,
        model_name: str,
        question_path: str,
        validator_class,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        fork_url: str = "https://bsc-testnet.drpc.org",
        test_mode: bool = False,
        test_code_path: Optional[str] = None
    ):
        """
        初始化控制器
        
        Args:
            model_name: LLM 模型名称 (例如: "anthropic/claude-sonnet-4", "gpt-4")
            question_path: 问题配置文件路径
            validator_class: 验证器类
            api_key: API key (如果为 None 则使用环境变量)
            base_url: 自定义 API base URL (可选)
            fork_url: BSC RPC URL (默认: testnet)
            test_mode: 测试模式，使用预先编写的代码而不是调用 LLM
            test_code_path: 测试代码路径（仅测试模式有效）
        """
        self.model_name = model_name
        self.question_path = question_path
        self.validator_class = validator_class
        self.api_key = api_key
        self.base_url = base_url
        self.fork_url = fork_url
        self.test_mode = test_mode
        self.test_code_path = test_code_path
        
        # 加载系统配置
        self.system_config = self._load_system_config()
        
        # 加载问题配置
        self.question = self._load_question()
        
        # 初始化参数生成器
        self.param_generator = ParameterGenerator()
        
        # 生成随机参数值
        self.generated_params = self._generate_parameters()
        
        # 初始化 LLM
        self.llm = self._init_llm(model_name, api_key, base_url)
        
        # 存储结果
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
        重新生成需要环境的参数（method='from_env'）
        
        Args:
            env: QuestEnvironment实例
        """
        params_config = self.question.get('parameters', {})
        
        # 检查是否有需要从环境获取的参数
        has_env_params = False
        env_param_names = []
        for param_name, param_config in params_config.items():
            generation_config = param_config.get('generation', {})
            if generation_config.get('method') == 'from_env':
                has_env_params = True
                env_param_names.append(param_name)
        
        if not has_env_params:
            return
        
        print(f"🔄 重新生成环境参数: {', '.join(env_param_names)}")
        
        # 重新创建带环境的参数生成器
        env_param_generator = ParameterGenerator(environment=env)
        
        # 重新生成所有参数
        new_params = env_param_generator.generate_parameters(params_config)
        
        # 显示更新的参数
        for param_name in env_param_names:
            old_value = self.generated_params.get(param_name, 'N/A')
            new_value = new_params.get(param_name, 'N/A')
            print(f"  • {param_name}: {old_value[:10]}... → {new_value}")
        
        # 更新参数
        self.generated_params.update(new_params)
        
        # 重新生成自然语言提示
        self.result['natural_language_prompt'] = self._generate_natural_language_prompt()
        print()
    
    def _init_llm(
        self,
        model_name: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        """
        初始化 LLM 客户端
        
        Args:
            model_name: 模型名称
            api_key: API key
            base_url: 自定义 API base URL
            
        Returns:
            LLM 客户端实例
        """
        if not model_name:
            raise ValueError("模型名称不能为空")
        
        llm_kwargs = {'model': model_name, 'temperature': 0.7}
        
        # 优先级 1: 自定义 base_url
        if base_url:
            print(f"🔄 使用自定义 API: {base_url}")
            print(f"   模型: {model_name}")
            if api_key:
                llm_kwargs['api_key'] = api_key
            llm_kwargs['base_url'] = base_url
            return ChatOpenAI(**llm_kwargs)
        
        # 优先级 2: OpenRouter (模型名包含 '/')
        if '/' in model_name:
            print(f"🔄 使用 OpenRouter")
            print(f"   模型: {model_name}")
            if api_key:
                llm_kwargs['api_key'] = api_key
                if not api_key.startswith('sk-or-v1-'):
                    print(f"⚠️  警告: OpenRouter API key 通常以 'sk-or-v1-' 开头")
                    print(f"   您的 key 开头: {api_key[:10]}...")
            else:
                print(f"⚠️  警告: 未提供 OpenRouter API key")
            
            llm_kwargs['base_url'] = "https://openrouter.ai/api/v1"
            llm_kwargs['default_headers'] = {
                "HTTP-Referer": "https://github.com/bsc-quest-bench",
                "X-Title": "BSC Quest Bench"
            }
            return ChatOpenAI(**llm_kwargs)
        
        # 优先级 3: 标准 provider
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
        Generate system prompt with four parts:
        1. Role prompt (same for all questions)
        2. Environment description (same for all questions)
        3. Question-specific context (optional, from question description)
        4. Natural language prompt (unique per question, with random values)
        """
        # Part 1: Role prompt (支持数组或字符串格式)
        role_prompt_raw = self.system_config['role_prompt']
        role_prompt = '\n'.join(role_prompt_raw) if isinstance(role_prompt_raw, list) else role_prompt_raw
        
        # Part 2: Environment description (支持数组或字符串格式)
        env_description_raw = self.system_config['environment_description']
        env_description = '\n'.join(env_description_raw) if isinstance(env_description_raw, list) else env_description_raw
        
        # Part 3: Question-specific context (optional, from description field)
        question_context = ""
        if 'description' in self.question:
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
        提取代码块
        
        Args:
            text: LLM 响应文本
            
        Returns:
            代码块列表
        """
        pattern = r'```(?:typescript|ts|javascript|js)?\s*\n(.*?)```'
        matches = re.findall(pattern, text, re.DOTALL)
        return [match.strip() for match in matches if match.strip()]
    
    def _load_test_code(self) -> str:
        """
        加载测试代码并替换参数占位符
        
        Returns:
            替换参数后的代码
        """
        if not self.test_code_path:
            raise ValueError("Test mode enabled but no test_code_path provided")
        
        # 读取测试代码
        with open(self.test_code_path, 'r', encoding='utf-8') as f:
            code = f.read()
        
        # 替换参数占位符
        for param_name, param_value in self.generated_params.items():
            placeholder = f"{{{{{param_name}}}}}"  # {{param_name}}
            code = code.replace(placeholder, str(param_value))
        
        return code
    
    def _save_code_to_temp_file(self, code: str) -> str:
        """
        保存代码到临时文件
        
        Args:
            code: TypeScript 代码
            
        Returns:
            临时文件路径
        """
        # 使用 skill_runner/temp/ 目录而不是系统 /tmp/
        # 这样 Bun 能正确解析 node_modules
        timestamp = int(time.time() * 1000)
        project_root = Path(__file__).parent.parent
        temp_dir = project_root / 'bsc_gym_env' / 'skill_runner' / 'temp'
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        code_file = temp_dir / f'temp_skill_{timestamp}.ts'
        
        with open(code_file, 'w', encoding='utf-8') as f:
            f.write(code)
        
        return str(code_file)
    
    async def run(self) -> Dict[str, Any]:
        """
        运行单轮评估
        
        Returns:
            评估结果字典
        """
        print("="*80)
        print("BSC Quest Bench - 单轮评估")
        print("="*80)
        print(f"问题ID: {self.question['id']}")
        print(f"模型: {self.model_name}")
        print(f"难度: {self.question['difficulty']}")
        print("="*80)
        print()
        
        self.result['start_time'] = datetime.now().isoformat()
        
        # 1. 启动环境
        print("🔧 启动环境...")
        env = QuestEnvironment(fork_url=self.fork_url)
        env_info = env.start()
        print()
        
        # 1.5 重新生成需要环境的参数（如 from_env）
        self._regenerate_env_parameters(env)
        
        try:
            # 2. 显示生成的参数
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
            
            # 3. 获取代码：测试模式或 LLM 生成
            if self.test_mode:
                # 测试模式：从文件加载代码
                print("🧪 TEST MODE: Loading code from test file...")
                code = self._load_test_code()
                self.result['llm_response'] = "[TEST MODE] Code loaded from file"
                self.result['extracted_code'] = code
                print(f"✅ Test code loaded from: {self.test_code_path}")
                print()
            else:
                # 正常模式：调用 LLM
                print("🤖 Calling LLM to generate code...")
                messages = [
                    SystemMessage(content=system_prompt)
                ]
                
                response = await self.llm.ainvoke(messages)
                self.result['llm_response'] = response.content
                
                print(f"✅ LLM response received ({len(response.content)} characters)")
                print()
                
                # 4. 提取代码块
                print("📝 提取代码块...")
                code_blocks = self.extract_code_blocks(response.content)
                
                if not code_blocks:
                    error_msg = "未找到 TypeScript 代码块"
                    print(f"❌ {error_msg}")
                    self.result['error'] = error_msg
                    return self.result
                
                code = code_blocks[0]
                self.result['extracted_code'] = code
                print(f"✅ 提取到 {len(code_blocks)} 个代码块")
                print()
            
            print("─"*80)
            print("提取的代码:")
            print("─"*80)
            print(code)
            print("─"*80)
            print()
            
            # 5. 执行代码生成交易对象
            print("⚙️  执行 TypeScript 代码...")
            from .skill_manager.ts_skill_manager import TypeScriptSkillManager
            
            skill_manager = TypeScriptSkillManager(use_bun=True)
            code_file = self._save_code_to_temp_file(code)
            
            try:
                tx_result = skill_manager.execute_skill(
                    code_file=code_file,
                    provider_url=env_info['rpc_url'],
                    agent_address=env_info['test_address'],
                    deployed_contracts={}
                )
                
                if not tx_result.get('success'):
                    error_msg = tx_result.get('error', '未知错误')
                    print(f"❌ TypeScript 执行失败: {error_msg}")
                    self.result['error'] = error_msg
                    return self.result
                
                tx = tx_result['tx_object']
                print(f"✅ 交易对象生成成功")
                print(f"   To: {tx.get('to')}")
                print(f"   Value: {tx.get('value')}")
                print()
                
            finally:
                import os
                if os.path.exists(code_file):
                    os.unlink(code_file)
            
            # 6. 创建执行器并执行交易
            print("🔗 执行交易...")
            executor = QuestExecutor(
                w3=env.w3,
                private_key=env_info['test_private_key']
            )
            
            # 创建验证器
            validator = self._create_validator(self.generated_params)
            
            # 准备 token 相关参数（如果是 ERC20 操作或 WBNB 操作）
            token_address = None
            target_address_for_token = None
            spender_address = None
            nft_address = None
            nft_token_id = None
            operator_address = None
            nft_type = None
            counter_contract_address = None
            message_board_contract_address = None
            proxy_address = None
            implementation_address = None
            expected_value = None
            
            if self.question.get('subcategory') == 'erc20_operations':
                token_address = self.generated_params.get('token_address')
                target_address_for_token = self.generated_params.get('to_address')
                spender_address = self.generated_params.get('spender_address')
            elif self.question.get('id') in ['wbnb_deposit', 'wbnb_withdraw']:
                # WBNB deposit/withdraw 需要查询 WBNB token 余额
                token_address = self.generated_params.get('wbnb_address')
            elif self.question.get('subcategory') == 'flashloan':
                # 闪电贷需要查询 token 余额（用于验证费用支付）
                token_address = self.generated_params.get('token_address')
            elif self.question.get('id') == 'contract_call_simple':
                # SimpleCounter 合约需要查询 counter 值
                counter_contract_address = self.generated_params.get('contract_address')
            elif self.question.get('id') == 'contract_call_with_params':
                # MessageBoard 合约需要查询 message 值
                message_board_contract_address = self.generated_params.get('contract_address')
            elif self.question.get('subcategory') == 'delegate_call':
                # DelegateCall 需要查询 proxy 和 implementation 的值
                proxy_address = self.generated_params.get('proxy_address')
                implementation_address = self.generated_params.get('implementation_address')
                expected_value = self.generated_params.get('value')
            elif self.question.get('subcategory') == 'nft_operations':
                # NFT 操作需要查询 NFT 所有权
                nft_address = self.generated_params.get('nft_address')
                nft_token_id = self.generated_params.get('token_id')
                operator_address = self.generated_params.get('operator_address')
                
                # 根据问题 ID 判断 NFT 类型
                question_id = self.question.get('id', '')
                if 'erc1155' in question_id:
                    nft_type = 'erc1155'
                    # ERC1155 transfer 操作还需要查询目标地址的余额
                    target_address_for_token = self.generated_params.get('to_address')
                elif 'erc721' in question_id:
                    nft_type = 'erc721'
                else:
                    nft_type = None
            
            # 执行交易
            execution_result = executor.execute_transaction(
                tx,
                validator,
                token_address=token_address,
                target_address_for_token=target_address_for_token,
                spender_address=spender_address,
                nft_address=nft_address,
                nft_token_id=nft_token_id,
                operator_address=operator_address,
                nft_type=nft_type,
                counter_contract_address=counter_contract_address,
                message_board_contract_address=message_board_contract_address,
                proxy_address=proxy_address,
                implementation_address=implementation_address,
                expected_value=expected_value
            )
            
            self.result['execution_success'] = execution_result['success']
            
            if execution_result['success']:
                self.result['validation_result'] = execution_result['validation']
                print()
                print("="*80)
                print("📊 评估结果")
                print("="*80)
                print(f"✅ 交易执行成功")
                print(f"验证通过: {'✅' if execution_result['validation']['passed'] else '❌'}")
                print(f"得分: {execution_result['validation']['score']}/{execution_result['validation']['max_score']}")
                print("="*80)
            else:
                error_msg = execution_result.get('error', '未知错误')
                print(f"❌ 交易执行失败: {error_msg}")
                self.result['error'] = error_msg
            
        finally:
            # 清理环境
            print("\n🧹 清理环境...")
            env.stop()
        
        self.result['end_time'] = datetime.now().isoformat()
        return self.result
    
    def _create_validator(self, params: Dict[str, Any]):
        """
        创建验证器实例
        
        Args:
            params: Generated parameters for this test case
            
        Returns:
            验证器实例
        """
        # validator_class 应该是一个工厂函数
        # 它接受 params 并返回验证器实例
        if callable(self.validator_class):
            return self.validator_class(**params)
        else:
            raise ValueError("validator_class must be callable")
    
    def save_result(self, output_path: str):
        """
        保存结果到文件
        
        Args:
            output_path: 输出文件路径
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.result, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ 结果已保存到: {output_path}")

