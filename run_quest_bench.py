"""
Run BSC Quest Bench with a specific LLM model

Usage:
    # Run all atomic problem tests
    python run_quest_bench.py --model gpt-4o --type atomic
    
    # Run composite problem tests (TODO)
    python run_quest_bench.py --model claude-3-sonnet --type composite
    
    # Run specific problems
    python run_quest_bench.py --model gemini-pro --questions bnb_transfer_basic swap_exact_bnb_for_tokens
    
    # Specify number of questions
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
from bsc_quest_bench.validators import CompositeValidator
import glob

# Helper functions to work with question bank
def get_all_atomic_question_ids() -> List[str]:
    """Get all atomic question IDs from question bank (excludes composite_problems)"""
    question_files = glob.glob(str(project_root / 'bsc_quest_bench' / 'question_bank' / '**' / '*.json'), recursive=True)
    question_ids = []
    for filepath in question_files:
        # Exclude composite_problems directory
        if 'composite_problems' in filepath:
            continue
        filename = Path(filepath).stem
        question_ids.append(filename)
    return sorted(question_ids)


def get_all_composite_question_ids() -> List[str]:
    """Get all composite question IDs from question bank"""
    question_files = glob.glob(str(project_root / 'bsc_quest_bench' / 'question_bank' / 'composite_problems' / '*.json'), recursive=True)
    question_ids = []
    for filepath in question_files:
        filename = Path(filepath).stem
        question_ids.append(filename)
    return sorted(question_ids)


def get_all_question_ids() -> List[str]:
    """Get all question IDs from question bank (atomic + composite)"""
    return sorted(get_all_atomic_question_ids() + get_all_composite_question_ids())

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
        'erc20_transferfrom_basic': ERC20TransferFromBasicValidator,
        'query_bnb_balance': QueryBNBBalanceValidator,
        'query_erc20_balance': QueryERC20BalanceValidator,
        'query_erc20_allowance': QueryERC20AllowanceValidator,
        'query_nft_approval_status': QueryNFTApprovalStatusValidator,
        'query_pair_reserves': QueryPairReservesValidator,
        'query_swap_output_amount': QuerySwapOutputAmountValidator,
        'query_swap_input_amount': QuerySwapInputAmountValidator,
        'query_staked_amount': QueryStakedAmountValidator,
        'query_pending_rewards': QueryPendingRewardsValidator,
        'query_token_metadata': QueryTokenMetadataValidator,
        'query_token_total_supply': QueryTokenTotalSupplyValidator,
        'query_nft_owner': QueryNFTOwnerValidator,
        'query_nft_token_uri': QueryNFTTokenURIValidator,
        'query_nft_balance': QueryNFTBalanceValidator,
        'query_current_block_number': QueryCurrentBlockNumberValidator,
        'query_gas_price': QueryGasPriceValidator,
        'query_transaction_count_nonce': QueryTransactionCountNonceValidator
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


class TeeWriter:
    """Writer that outputs to both console and file simultaneously"""
    
    def __init__(self, original_stream, log_file):
        self.original_stream = original_stream
        self.log_file = log_file
        self.encoding = getattr(original_stream, 'encoding', 'utf-8') or 'utf-8'
    
    def write(self, message):
        # Write to original stream (console)
        self.original_stream.write(message)
        # Write to log file
        if self.log_file and not self.log_file.closed:
            try:
                self.log_file.write(message)
                self.log_file.flush()  # Ensure real-time writing
            except Exception:
                pass  # Ignore write errors to log file
    
    def flush(self):
        self.original_stream.flush()
        if self.log_file and not self.log_file.closed:
            try:
                self.log_file.flush()
            except Exception:
                pass
    
    def isatty(self):
        return self.original_stream.isatty() if hasattr(self.original_stream, 'isatty') else False
    
    def fileno(self):
        return self.original_stream.fileno() if hasattr(self.original_stream, 'fileno') else -1


class QuestBenchRunner:
    """Quest Bench Evaluation Runner"""
    
    def __init__(self, model_name: str, api_key: Optional[str] = None, 
                 base_url: Optional[str] = None, fork_url: str = "https://bsc-testnet.drpc.org",
                 run_index: int = 0, naive_mode: bool = False):
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.fork_url = fork_url
        self.run_index = run_index
        self.naive_mode = naive_mode
        
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
        """Run atomic problem tests only"""
        
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
    
    async def run_all_tests(self, atomic_ids: List[str], composite_ids: List[str], max_questions: Optional[int] = None):
        """Run all tests: atomic first, restart Anvil, then composite with 10s intervals"""
        import asyncio
        
        total_questions = len(atomic_ids) + len(composite_ids)
        
        print("\n" + "="*80)
        print("🧪 BSC QUEST BENCH - Full Evaluation (Atomic + Composite)")
        print("="*80)
        print(f"Model: {self.model_name}")
        print(f"Total Questions: {total_questions}")
        print(f"  - Atomic: {len(atomic_ids)}")
        print(f"  - Composite: {len(composite_ids)}")
        if max_questions:
            print(f"Max Questions: {max_questions} (randomly sampled)")
        print(f"Fork URL: {self.fork_url}")
        print(f"Strategy: Atomic → Restart Anvil → Composite (10s intervals)")
        print("="*80 + "\n")
        
        # Sample questions if max_questions is specified
        if max_questions:
            # Proportionally sample from both types
            atomic_ratio = len(atomic_ids) / total_questions
            max_atomic = max(1, int(max_questions * atomic_ratio))
            max_composite = max_questions - max_atomic
            
            if max_atomic < len(atomic_ids):
                atomic_ids = random.sample(atomic_ids, max_atomic)
            if max_composite < len(composite_ids):
                composite_ids = random.sample(composite_ids, max_composite)
            
            print(f"📝 Randomly selected: {len(atomic_ids)} atomic + {len(composite_ids)} composite\n")
        
        # Initialize extended results tracking
        self.results['atomic_success'] = 0
        self.results['atomic_failure'] = 0
        self.results['composite_success'] = 0
        self.results['composite_failure'] = 0
        
        # ========================================
        # Phase 1: Run Atomic Problems
        # ========================================
        print("\n" + "="*80)
        print("📦 PHASE 1: ATOMIC PROBLEMS")
        print("="*80 + "\n")
        
        print("🔧 Starting Anvil environment for atomic tests...")
        env = QuestEnvironment(fork_url=self.fork_url)
        env.start()
        print("✅ Environment started successfully\n")
        
        global_idx = 0
        
        try:
            for idx, question_id in enumerate(atomic_ids, 1):
                global_idx += 1
                print("\n" + "="*80)
                print(f"📝 [Atomic {idx}/{len(atomic_ids)}] (Total {global_idx}/{total_questions}): {question_id}")
                print("="*80)
                
                result = await self._run_single_question(question_id, env)
                result['type'] = 'atomic'
                self.results['questions'].append(result)
                
                # Update statistics
                if result['execution_success'] and result['validation_passed']:
                    self.results['success_count'] += 1
                    self.results['atomic_success'] += 1
                else:
                    self.results['failure_count'] += 1
                    self.results['atomic_failure'] += 1
                
                self.results['scores'].append(result['score'])
                self.results['total_score'] += result['score']
                
                # Print summary
                status = "✅" if result['validation_passed'] else "❌"
                print(f"\n{status} Result: {result['score']}/{result['max_score']} "
                      f"({result['score']/result['max_score']*100:.0f}%)")
                
                # Reset environment for next atomic test
                if idx < len(atomic_ids):
                    print(f"\n🔄 Resetting environment...")
                    env.reset()
            
            # Print atomic phase summary
            print("\n" + "="*80)
            print("📊 PHASE 1 SUMMARY: ATOMIC PROBLEMS")
            print("="*80)
            print(f"Atomic Tests: {len(atomic_ids)}")
            print(f"✅ Passed: {self.results['atomic_success']}")
            print(f"❌ Failed: {self.results['atomic_failure']}")
            print("="*80)
            
            # ========================================
            # Phase 2: Run Composite Problems
            # ========================================
            phase_stopped = False
            if len(composite_ids) > 0:
                # Reset Anvil state for composite phase (no restart, just full reset)
                print("\n" + "="*80)
                print("🔄 RESETTING ANVIL STATE FOR COMPOSITE PHASE")
                print("="*80)
                
                print("🩺 Checking Anvil health before composite phase...")
                if not env.check_health(timeout=10):
                    print(f"⚠️  Anvil is unresponsive, attempting full environment reset...")
                    env.print_diagnostics()
                    # Try to reset even if unresponsive
                    if env.reset():
                        print(f"✅ Environment reset successfully after unresponsive state")
                    else:
                        print(f"⚠️  Reset failed, skipping composite phase")
                        phase_stopped = True
                else:
                    print(f"✅ Anvil is healthy")
                    
                    print("🔄 Performing full environment reset...")
                    if not env.reset():
                        print(f"⚠️  Reset failed, skipping composite phase")
                        env.print_diagnostics()
                        phase_stopped = True
                    else:
                        print("✅ Environment reset successfully")
                
                if not phase_stopped:
                    print("⏳ Waiting 10 seconds before starting composite tests...")
                    await asyncio.sleep(10)
            
            # Run composite tests only if phase was not stopped
            if not phase_stopped and len(composite_ids) > 0:
                print("\n" + "="*80)
                print("🔗 PHASE 2: COMPOSITE PROBLEMS")
                print("="*80 + "\n")
                
                composite_sleep = 10  # 10 seconds between composite tests
                
                for idx, question_id in enumerate(composite_ids, 1):
                    global_idx += 1
                    print("\n" + "="*80)
                    print(f"📝 [Composite {idx}/{len(composite_ids)}] (Total {global_idx}/{total_questions}): {question_id}")
                    print("="*80)
                    
                    result = await self._run_single_question(question_id, env, is_composite=True)
                    result['type'] = 'composite'
                    self.results['questions'].append(result)
                    
                    # Update statistics
                    if result['execution_success'] and result['validation_passed']:
                        self.results['success_count'] += 1
                        self.results['composite_success'] += 1
                    else:
                        self.results['failure_count'] += 1
                        self.results['composite_failure'] += 1
                    
                    self.results['scores'].append(result['score'])
                    self.results['total_score'] += result['score']
                    
                    # Print summary
                    status = "✅" if result['validation_passed'] else "❌"
                    print(f"\n{status} Result: {result['score']}/{result['max_score']} "
                          f"({result['score']/result['max_score']*100:.0f}%)")
                    
                    # Reset environment for next composite test with longer delay
                    if idx < len(composite_ids):
                        print(f"\n🔄 Resetting environment...")
                        env.reset()
                        print(f"💤 Sleeping {composite_sleep}s before next composite test...")
                        await asyncio.sleep(composite_sleep)
                
                # Print composite phase summary
                print("\n" + "="*80)
                print("📊 PHASE 2 SUMMARY: COMPOSITE PROBLEMS")
                print("="*80)
                print(f"Composite Tests: {len(composite_ids)}")
                print(f"✅ Passed: {self.results['composite_success']}")
                print(f"❌ Failed: {self.results['composite_failure']}")
                print("="*80)
                
        finally:
            print("\n🧹 Stopping Anvil environment...")
            env.stop()
        
        # Calculate final statistics
        self.results['end_time'] = datetime.now().isoformat()
        if self.results['scores']:
            self.results['average_score'] = self.results['total_score'] / len(self.results['scores'])
        
        return self.results
    
    async def _run_single_question(self, question_id: str, env: QuestEnvironment, is_composite: bool = False) -> Dict[str, Any]:
        """Run single problem test (atomic or composite)"""
        
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
        
        # Create validator factory based on problem type
        if is_composite:
            # Composite problem: use CompositeValidator
            print(f"🔗 Using CompositeValidator for {question_id}")
            
            def validator_factory(**kwargs):
                validator = CompositeValidator(kwargs.get('agent_address', ''))
                validator.load_composite_definition(question_id)
                return validator
        else:
            # Atomic problem: use VALIDATOR_REGISTRY
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
            env=env,
            naive_mode=self.naive_mode
        )
        
        # Run evaluation
        try:
            result = await controller.run()
            
            # Handle None result (execution failed before returning result)
            if result is None:
                print(f"❌ Error: controller.run() returned None for question {question_id}")
                return {
                    'question_id': question_id,
                    'execution_success': False,
                    'validation_passed': False,
                    'score': 0,
                    'max_score': 100,
                    'error': 'Execution failed: controller.run() returned None'
                }
            
            # Safely extract validation_result (handle None case)
            validation_result = result.get('validation_result') or {}
            
            return {
                'question_id': result['question_id'],
                'execution_success': result['execution_success'],
                'validation_passed': validation_result.get('passed', False),
                'score': validation_result.get('score', 0),
                'max_score': validation_result.get('max_score', 100),
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
        """Save evaluation results"""
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
        """Print evaluation summary"""
        print("\n" + "="*80)
        print("📊 FINAL RESULTS")
        print("="*80)
        print(f"Model: {self.model_name}")
        print(f"Total Questions: {len(self.results['questions'])}")


        # Show breakdown by type if available
        if 'atomic_success' in self.results:
            atomic_total = self.results.get('atomic_success', 0) + self.results.get('atomic_failure', 0)
            composite_total = self.results.get('composite_success', 0) + self.results.get('composite_failure', 0)
            print(f"  - Atomic: {atomic_total} (✅ {self.results.get('atomic_success', 0)} / ❌ {self.results.get('atomic_failure', 0)})")
            print(f"  - Composite: {composite_total} (✅ {self.results.get('composite_success', 0)} / ❌ {self.results.get('composite_failure', 0)})")
        
        print(f"\n✅ Successful: {self.results['success_count']}")
        print(f"❌ Failed: {self.results['failure_count']}")
        print(f"\n💯 Total Score: {self.results['total_score']:.1f}")
        print(f"📊 Average Score: {self.results['average_score']:.1f}")

        if self.results['scores']:
            success_rate = self.results['success_count'] / len(self.results['questions']) * 100
            print(f"📈 Success Rate: {success_rate:.1f}%")
        
        # Detailed scores by question (grouped by type if available)
        print(f"\n📋 Detailed Scores:")
        print("-"*80)
        
        # Check if we have type information
        has_types = any(r.get('type') for r in self.results['questions'])
        
        if has_types:
            # Print atomic results first
            atomic_results = [r for r in self.results['questions'] if r.get('type') == 'atomic']
            if atomic_results:
                print("--- ATOMIC PROBLEMS ---")
                for result in atomic_results:
                    status = "✅" if result['validation_passed'] else "❌"
                    score_pct = result['score'] / result['max_score'] * 100 if result['max_score'] > 0 else 0
                    print(f"{status} {result['question_id']:<40} {result['score']:>3}/{result['max_score']:<3} ({score_pct:.0f}%)")
            
            # Print composite results
            composite_results = [r for r in self.results['questions'] if r.get('type') == 'composite']
            if composite_results:
                print("\n--- COMPOSITE PROBLEMS ---")
                for result in composite_results:
                    status = "✅" if result['validation_passed'] else "❌"
                    score_pct = result['score'] / result['max_score'] * 100 if result['max_score'] > 0 else 0
                    print(f"{status} {result['question_id']:<40} {result['score']:>3}/{result['max_score']:<3} ({score_pct:.0f}%)")
        else:
            # No type info, print all together
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
  # Run all problems (atomic + composite, default)
  python run_quest_bench.py --model gpt-4o
  
  # Run only atomic problems
  python run_quest_bench.py --model gpt-4o --type atomic
  
  # Run only composite problems
  python run_quest_bench.py --model claude-3-sonnet --type composite
  
  # Run 10 random problems (proportionally sampled)
  python run_quest_bench.py --model claude-3-sonnet --max-questions 10
  
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
        default='all',
        choices=['atomic', 'composite', 'all'],
        help='Problem type: atomic, composite, or all (default: all)'
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
    parser.add_argument(
        '--naive-mode',
        action='store_true',
        help='Naive mode: Include detailed implementation guidance in prompts (easier, default: False)'
    )
    
    args = parser.parse_args()
    
    # Setup log directory
    log_dir = Path("log")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model_name = args.model.replace('/', '_')
    
    # Create log file paths
    full_log_filename = f"quest_bench_{safe_model_name}_{args.run_index}_{timestamp}.log"
    failed_log_filename = f"quest_bench_{safe_model_name}_{args.run_index}_{timestamp}_failed.log"
    full_log_path = log_dir / full_log_filename
    failed_log_path = log_dir / failed_log_filename
    
    # Setup Tee output for full console log
    full_log_file = open(full_log_path, 'w', encoding='utf-8')
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    sys.stdout = TeeWriter(original_stdout, full_log_file)
    sys.stderr = TeeWriter(original_stderr, full_log_file)
    
    output_file = None
    failed_count = 0
    
    # Initialize failed log file with header
    with open(failed_log_path, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("BSC Quest Bench - Failed Tests Log\n")
        f.write("=" * 80 + "\n")
        f.write(f"Start Time: {datetime.now().isoformat()}\n")
        f.write(f"Model: {args.model}\n")
        f.write(f"Type: {args.type}\n")
        f.write(f"Run Index: {args.run_index}\n")
        f.write("=" * 80 + "\n\n")
    
    try:
        print("\n" + "="*80)
        print("🚀 BSC QUEST BENCH - LLM Evaluation System")
        print("="*80)
        print(f"Model: {args.model}")
        print(f"Type: {args.type}")
        print(f"Difficulty: {'Naive (with guidance)' if args.naive_mode else 'Normal (pure NL)'}")
        print(f"Fork URL: {args.fork_url}")
        print(f"📝 Full console log: {full_log_path}")
        print(f"📝 Failed tests log: {failed_log_path}")
        print("="*80 + "\n")
        
        # Create runner
        runner = QuestBenchRunner(
            model_name=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            fork_url=args.fork_url,
            run_index=args.run_index,
            naive_mode=args.naive_mode
        )
        
        # Determine questions to test
        if args.questions:
            question_ids = args.questions
            print(f"📝 Testing specified questions: {', '.join(question_ids)}\n")
            # For specific questions, run as atomic tests
            results = await runner.run_atomic_tests(question_ids, args.max_questions)
        elif args.type == 'all':
            # Run all tests: atomic first, then composite
            atomic_ids = get_all_atomic_question_ids()
            composite_ids = get_all_composite_question_ids()
            print(f"📝 Found {len(atomic_ids)} atomic + {len(composite_ids)} composite = {len(atomic_ids) + len(composite_ids)} total\n")
            results = await runner.run_all_tests(atomic_ids, composite_ids, args.max_questions)
        elif args.type == 'atomic':
            question_ids = get_all_atomic_question_ids()
            print(f"📝 Found {len(question_ids)} atomic problems\n")
            results = await runner.run_atomic_tests(question_ids, args.max_questions)
        elif args.type == 'composite':
            # Run composite only
            composite_ids = get_all_composite_question_ids()
            print(f"📝 Found {len(composite_ids)} composite problems\n")
            results = await runner.run_all_tests([], composite_ids, args.max_questions)
        else:
            print("❌ Unknown problem type")
            sys.exit(1)
        
        # Write failed tests to separate log file
        for question_result in results.get('questions', []):
            if not question_result.get('validation_passed', False):
                failed_count += 1
                with open(failed_log_path, 'a', encoding='utf-8') as f:
                    f.write(f"[{failed_count}] {question_result['question_id']}\n")
                    f.write("-" * 60 + "\n")
                    f.write(f"  Type: {question_result.get('type', 'unknown')}\n")
                    f.write(f"  Execution Success: {question_result.get('execution_success', False)}\n")
                    f.write(f"  Validation Passed: {question_result.get('validation_passed', False)}\n")
                    f.write(f"  Score: {question_result.get('score', 0)}/{question_result.get('max_score', 100)}\n")
                    if question_result.get('error'):
                        f.write(f"  Error: {question_result['error']}\n")
                    f.write("\n")
        
        # Finalize failed log
        if failed_count > 0:
            with open(failed_log_path, 'a', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write(f"End Time: {datetime.now().isoformat()}\n")
                f.write(f"Total Failed: {failed_count}\n")
                f.write("=" * 80 + "\n")
            print(f"\n❌ {failed_count} test(s) failed. See: {failed_log_path}")
        else:
            # All tests passed, remove the empty failed log file
            if failed_log_path.exists():
                failed_log_path.unlink()
            print("\n✅ All tests passed! No failed tests log file created.")
        
        # Save results
        output_file = runner.save_results(args.output_dir)
        
        # Print summary
        runner.print_summary()
        
        print(f"\n📁 Results saved to: {output_file}")
        print(f"📁 Full log saved to: {full_log_path}")
        print("="*80 + "\n")
    
    finally:
        # Restore stdout and stderr
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        
        if full_log_file and not full_log_file.closed:
            full_log_file.close()
        
        # Final summary (console only)
        print(f"\n{'='*80}")
        print(f"✅ Quest Bench Completed")
        print(f"{'='*80}")
        print(f"📁 Full log saved to: {full_log_path}")
        if failed_count > 0:
            print(f"📁 Failed tests log saved to: {failed_log_path}")
        if output_file:
            print(f"📁 Results saved to: {output_file}")
        print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
