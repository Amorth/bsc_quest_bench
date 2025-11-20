"""
Run BSC Quest Bench with a specific LLM model

Usage:
    # 运行所有原子问题测试
    python run_quest_bench.py --model gpt-4o --type atomic
    
    # 运行组合问题测试（TODO）
    python run_quest_bench.py --model claude-3-sonnet --type composite
    
    # 运行特定问题
    python run_quest_bench.py --model gemini-pro --questions bnb_transfer_basic swap_exact_bnb_for_tokens
    
    # 指定问题数量
    python run_quest_bench.py --model gpt-4o --max-questions 10

All tests run in Anvil Fork Mode with complete environment isolation.
"""

import argparse
import asyncio
import sys
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Direct imports from current directory
from bsc_quest_bench.quest_controller import QuestController
from bsc_quest_bench.quest_env import QuestEnvironment
from bsc_quest_bench.validators import *
import glob

# Helper functions to work with question bank
def get_all_question_ids() -> List[str]:
    """Get all question IDs from question bank"""
    question_files = glob.glob(str(project_root / 'bsc_quest_bench' / 'question_bank' / '**' / '*.json'), recursive=True)
    question_ids = []
    for filepath in question_files:
        filename = Path(filepath).stem
        question_ids.append(filename)
    return sorted(question_ids)

def get_question_path(question_id: str) -> Optional[Path]:
    """Get path to question JSON file"""
    question_files = glob.glob(str(project_root / 'bsc_quest_bench' / 'question_bank' / '**' / f'{question_id}.json'), recursive=True)
    if question_files:
        return Path(question_files[0])
    return None

# Validator Registry - maps question_id to validator class
VALIDATOR_REGISTRY = {
        'bnb_transfer_basic': BNBTransferValidator,
        'bnb_transfer_percentage': BNBTransferPercentageValidator,
        'bnb_transfer_with_message': BNBTransferWithMessageValidator,
        'bnb_transfer_to_contract': BNBTransferToContractValidator,
        'bnb_transfer_max_amount': BNBTransferMaxAmountValidator,
        'erc20_transfer_fixed': ERC20TransferValidator,
        'erc20_transfer_percentage': ERC20TransferPercentageValidator,
        'erc20_approve': ERC20ApproveValidator,
        'erc20_increase_allowance': ERC20IncreaseAllowanceValidator,
        'erc20_decrease_allowance': ERC20DecreaseAllowanceValidator,
        'erc20_burn': ERC20BurnValidator,
        'erc20_revoke_approval': ERC20RevokeApprovalValidator,
        'erc20_transfer_max_amount': ERC20TransferMaxAmountValidator,
        'erc20_transfer_with_callback_1363': ERC20TransferWithCallback1363Validator,
        'erc20_approve_and_call_1363': ERC20ApproveAndCall1363Validator,
        'erc20_permit': ERC20PermitValidator,
        'erc20_flashloan': ERC20FlashLoanValidator,
        'erc1155_transfer_single': ERC1155TransferSingleValidator,
        'erc1155_safe_transfer_with_data': ERC1155SafeTransferWithDataValidator,
        'erc721_transfer': ERC721TransferValidator,
        'erc721_safe_transfer': ERC721SafeTransferValidator,
        'erc721_approve': ERC721ApproveValidator,
        'erc721_set_approval_for_all': ERC721SetApprovalForAllValidator,
        'wbnb_deposit': WBNBDepositValidator,
        'wbnb_withdraw': WBNBWithdrawValidator,
        'contract_call_simple': ContractCallSimpleValidator,
        'contract_call_with_value': ContractCallWithValueValidator,
        'contract_call_with_params': ContractCallWithParamsValidator,
        'contract_delegate_call': ContractDelegateCallValidator,
        'contract_payable_fallback': ContractPayableFallbackValidator,
        'swap_exact_bnb_for_tokens': SwapExactBNBForTokensValidator,
        'swap_exact_tokens_for_bnb': SwapExactTokensForBNBValidator,
        'swap_exact_tokens_for_tokens': SwapExactTokensForTokensValidator,
        'swap_tokens_for_exact_tokens': SwapTokensForExactTokensValidator,
        'swap_multihop_routing': SwapMultihopRoutingValidator,
        'add_liquidity_bnb_token': AddLiquidityBNBTokenValidator,
        'add_liquidity_tokens': AddLiquidityTokensValidator,
        'remove_liquidity_tokens': RemoveLiquidityTokensValidator,
        'remove_liquidity_bnb_token': RemoveLiquidityBNBTokenValidator,
        'stake_single_token': StakeSingleTokenValidator,
        'stake_lp_tokens': StakeLPTokensValidator,
        'unstake_lp_tokens': UnstakeLPTokensValidator,
        'harvest_rewards': HarvestRewardsValidator,
        'emergency_withdraw': EmergencyWithdrawValidator,
        'erc20_transferfrom_basic': ERC20TransferFromBasicValidator
}

def create_validator_factory(question_id: str):
    """Create validator for a question"""
    import inspect
    
    validator_class = VALIDATOR_REGISTRY.get(question_id)
    if not validator_class:
        raise ValueError(f"No validator found for question: {question_id}")

    def factory(**params):
        # Get the validator's __init__ signature
        sig = inspect.signature(validator_class.__init__)
        # Filter params to only include those accepted by __init__
        valid_params = {}
        for param_name, param_value in params.items():
            if param_name in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            ):
                valid_params[param_name] = param_value
        return validator_class(**valid_params)

    return factory


class TeeOutput:
    """同时输出到控制台和文件"""
    def __init__(self, file, terminal):
        self.file = file
        self.terminal = terminal
    
    def write(self, message):
        self.terminal.write(message)
        self.file.write(message)
        self.terminal.flush()
        self.file.flush()
    
    def flush(self):
        self.terminal.flush()
        self.file.flush()


class QuestBenchRunner:
    """Quest Bench 评估运行器"""
    
    def __init__(self, model_name: str, api_key: Optional[str] = None, 
                 base_url: Optional[str] = None, fork_url: str = "https://bsc-testnet.drpc.org",
                 run_index: int = 0):
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.fork_url = fork_url
        self.run_index = run_index
        
        # Results storage
        self.results = {
            'model_name': model_name,
            'run_index': run_index,
            'start_time': datetime.now().isoformat(),
            'questions': [],
            'scores': [],
            'total_score': 0,
            'average_score': 0,
            'success_count': 0,
            'failure_count': 0,
            'metadata': {
                'fork_url': fork_url,
                'base_url': base_url
            }
        }
    
    async def run_atomic_tests(self, question_ids: List[str], max_questions: Optional[int] = None):
        """运行原子问题测试"""
        
        print("\n" + "="*80)
        print("🧪 BSC QUEST BENCH - Atomic Problem Evaluation")
        print("="*80)
        print(f"Model: {self.model_name}")
        print(f"Total Questions: {len(question_ids)}")
        if max_questions:
            print(f"Testing: {max_questions} questions (randomly sampled)")
        print(f"Fork URL: {self.fork_url}")
        print("="*80 + "\n")
        
        # Sample questions if max_questions is specified
        if max_questions and max_questions < len(question_ids):
            question_ids = random.sample(question_ids, max_questions)
            print(f"📝 Randomly selected {max_questions} questions\n")
        
        # Start shared environment
        print("🔧 Starting shared Anvil environment...")
        env = QuestEnvironment(fork_url=self.fork_url)
        env.start()
        print("✅ Shared environment started successfully\n")
        
        try:
            for idx, question_id in enumerate(question_ids, 1):
                print("\n" + "="*80)
                print(f"📝 Question {idx}/{len(question_ids)}: {question_id}")
                print("="*80)
                
                result = await self._run_single_question(question_id, env)
                self.results['questions'].append(result)
                
                # Update statistics
                if result['execution_success'] and result['validation_passed']:
                    self.results['success_count'] += 1
                else:
                    self.results['failure_count'] += 1
                
                self.results['scores'].append(result['score'])
                self.results['total_score'] += result['score']
                
                # Print summary
                status = "✅" if result['validation_passed'] else "❌"
                print(f"\n{status} Result: {result['score']}/{result['max_score']} "
                      f"({result['score']/result['max_score']*100:.0f}%)")
                
                # Reset environment for next test
                if idx < len(question_ids):
                    print(f"\n🔄 Resetting environment...")
                    env.reset()
        
        finally:
            print("\n🧹 Cleaning up environment...")
            env.stop()
        
        # Calculate final statistics
        self.results['end_time'] = datetime.now().isoformat()
        if self.results['scores']:
            self.results['average_score'] = self.results['total_score'] / len(self.results['scores'])
        
        return self.results
    
    async def _run_single_question(self, question_id: str, env: QuestEnvironment) -> Dict[str, Any]:
        """运行单个问题测试"""
        
        # Find question file
        question_path = get_question_path(question_id)
        if not question_path:
            return {
                'question_id': question_id,
                'execution_success': False,
                'validation_passed': False,
                'score': 0,
                'max_score': 100,
                'error': f'Question {question_id} not found'
            }
        
        # Check validator
        if question_id not in VALIDATOR_REGISTRY:
            return {
                'question_id': question_id,
                'execution_success': False,
                'validation_passed': False,
                'score': 0,
                'max_score': 100,
                'error': f'No validator registered for {question_id}'
            }
        
        # Create validator factory
        try:
            validator_factory = create_validator_factory(question_id)
        except Exception as e:
            return {
                'question_id': question_id,
                'execution_success': False,
                'validation_passed': False,
                'score': 0,
                'max_score': 100,
                'error': f'Failed to create validator: {e}'
            }
        
        # Create controller
        controller = QuestController(
            model_name=self.model_name,
            question_path=str(question_path),
            validator_class=validator_factory,
            api_key=self.api_key,
            base_url=self.base_url,
            fork_url=self.fork_url,
            test_mode=False,  # Use LLM
            env=env
        )
        
        # Run evaluation
        try:
            result = await controller.run()
            
            return {
                'question_id': result['question_id'],
                'execution_success': result['execution_success'],
                'validation_passed': result.get('validation_result', {}).get('passed', False),
                'score': result.get('validation_result', {}).get('score', 0),
                'max_score': result.get('validation_result', {}).get('max_score', 100),
                'generated_params': result.get('generated_params', {}),
                'llm_response': result.get('llm_response', ''),
                'error': result.get('error')
            }
        except Exception as e:
            print(f"❌ Error running question {question_id}: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                'question_id': question_id,
                'execution_success': False,
                'validation_passed': False,
                'score': 0,
                'max_score': 100,
                'error': str(e)
            }
    
    def save_results(self, output_dir: str = "results") -> str:
        """保存评估结果"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_model_name = self.model_name.replace('/', '_')
        filename = f"quest_bench_{safe_model_name}_{self.run_index}_{timestamp}.json"
        filepath = output_path / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        return str(filepath)
    
    def print_summary(self):
        """打印评估摘要"""
        print("\n" + "="*80)
        print("📊 FINAL RESULTS")
        print("="*80)
        print(f"Model: {self.model_name}")
        print(f"Total Questions: {len(self.results['questions'])}")
        print(f"✅ Successful: {self.results['success_count']}")
        print(f"❌ Failed: {self.results['failure_count']}")
        print(f"\n💯 Total Score: {self.results['total_score']:.1f}")
        print(f"📊 Average Score: {self.results['average_score']:.1f}")
        
        if self.results['scores']:
            success_rate = self.results['success_count'] / len(self.results['questions']) * 100
            print(f"📈 Success Rate: {success_rate:.1f}%")
        
        # Detailed scores by question
        print(f"\n📋 Detailed Scores:")
        print("-"*80)
        for result in self.results['questions']:
            status = "✅" if result['validation_passed'] else "❌"
            score_pct = result['score'] / result['max_score'] * 100 if result['max_score'] > 0 else 0
            print(f"{status} {result['question_id']:<40} {result['score']:>3}/{result['max_score']:<3} ({score_pct:.0f}%)")
        
        print("="*80)


async def main():
    parser = argparse.ArgumentParser(
        description='Run BSC Quest Bench evaluation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all atomic problems
  python run_quest_bench.py --model gpt-4o --type atomic
  
  # Run 10 random atomic problems
  python run_quest_bench.py --model claude-3-sonnet --type atomic --max-questions 10
  
  # Run specific questions
  python run_quest_bench.py --model gemini-pro --questions bnb_transfer_basic swap_exact_bnb_for_tokens
  
  # Use custom API base URL (e.g., Alibaba Cloud)
  python run_quest_bench.py --model qwen-turbo --base-url https://dashscope.aliyuncs.com/compatible-mode/v1
        """
    )
    
    parser.add_argument(
        '--model',
        type=str,
        required=True,
        help='LLM model name (e.g., gpt-4o, claude-3-sonnet, gemini-pro)'
    )
    parser.add_argument(
        '--type',
        type=str,
        default='atomic',
        choices=['atomic', 'composite'],
        help='Problem type: atomic or composite (default: atomic)'
    )
    parser.add_argument(
        '--questions',
        nargs='+',
        help='Specific question IDs to test (space-separated)'
    )
    parser.add_argument(
        '--max-questions',
        type=int,
        help='Maximum number of questions to test (randomly sampled)'
    )
    parser.add_argument(
        '--run-index',
        type=int,
        default=0,
        help='Run index for this experiment'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='results',
        help='Directory to save results (default: results)'
    )
    parser.add_argument(
        '--api-key',
        type=str,
        default=None,
        help='API key for LLM provider. If not provided, will use environment variable.'
    )
    parser.add_argument(
        '--base-url',
        type=str,
        default=None,
        help='Custom API base URL (e.g., for Alibaba Cloud, Azure, etc.)'
    )
    parser.add_argument(
        '--fork-url',
        type=str,
        default='https://bsc-testnet.drpc.org',
        help='BSC RPC URL to fork with Anvil (default: DRPC BSC Testnet)'
    )
    
    args = parser.parse_args()
    
    # Setup log file
    log_dir = Path("log")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model_name = args.model.replace('/', '_')
    log_filename = f"quest_bench_{safe_model_name}_{args.run_index}_{timestamp}.log"
    log_filepath = log_dir / log_filename
    
    # Setup Tee output
    log_file = open(log_filepath, 'w', buffering=1)
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    sys.stdout = TeeOutput(log_file, original_stdout)
    sys.stderr = TeeOutput(log_file, original_stderr)
    
    output_file = None
    
    try:
        print("\n" + "="*80)
        print("🚀 BSC QUEST BENCH - LLM Evaluation System")
        print("="*80)
        print(f"Model: {args.model}")
        print(f"Type: {args.type}")
        print(f"Fork URL: {args.fork_url}")
        print(f"Log File: {log_filepath}")
        print("="*80 + "\n")
        
        # Create runner
        runner = QuestBenchRunner(
            model_name=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            fork_url=args.fork_url,
            run_index=args.run_index
        )
        
        # Determine questions to test
        if args.questions:
            question_ids = args.questions
            print(f"📝 Testing specified questions: {', '.join(question_ids)}\n")
        elif args.type == 'atomic':
            question_ids = get_all_question_ids()
            print(f"📝 Found {len(question_ids)} atomic problems\n")
        else:
            # TODO: Composite problems
            print("❌ Composite problems not yet implemented")
            sys.exit(1)
        
        # Run tests
        if args.type == 'atomic':
            results = await runner.run_atomic_tests(question_ids, args.max_questions)
        else:
            # TODO: Composite problems
            print("❌ Composite problems not yet implemented")
            sys.exit(1)
        
        # Save results
        output_file = runner.save_results(args.output_dir)
        
        # Print summary
        runner.print_summary()
        
        print(f"\n📁 Results saved to: {output_file}")
        print(f"📁 Log saved to: {log_filepath}")
        print("="*80 + "\n")
    
    finally:
        # Restore stdout and stderr
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_file.close()
        
        # Final summary (console only)
        print(f"\n{'='*80}")
        print(f"✅ Quest Bench 完成")
        print(f"{'='*80}")
        print(f"📁 Log saved to: {log_filepath}")
        if output_file:
            print(f"📁 Results saved to: {output_file}")
        print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())

