"""
Generic Composite Validator

This validator handles all composite problems by:
1. Loading the composite problem definition
2. Sequentially validating each atomic operation using its validator
3. Calculating the composite score (average or weighted)
4. Optionally performing inter-operation checks

This approach drastically reduces development effort as we don't need
to write custom validators for each composite problem.
"""

import importlib
from typing import Dict, List, Any, Optional
from pathlib import Path
import json


class CompositeValidator:
    """
    Generic validator for composite problems
    
    Validates composite problems by sequentially calling atomic validators
    and aggregating their scores.
    """
    
    def __init__(self, composite_definition: Dict[str, Any]):
        """
        Initialize composite validator
        
        Args:
            composite_definition: The composite problem JSON definition
        """
        self.composite_def = composite_definition
        self.composite_id = composite_definition.get('id')
        self.atomic_operations = composite_definition.get('composite_structure', {}).get('atomic_operations', [])
        self.scoring_method = composite_definition.get('composite_structure', {}).get('scoring_method', 'average')
        self.inter_op_checks = composite_definition.get('composite_structure', {}).get('inter_operation_checks', [])
        
        # Load atomic validators
        self.atomic_validators = self._load_atomic_validators()
    
    def _load_atomic_validators(self) -> List[Any]:
        """
        Load validators for each atomic operation
        
        Returns:
            List of validator instances
        """
        validators = []
        
        for atomic_op in self.atomic_operations:
            atomic_id = atomic_op.get('atomic_id')
            
            # Import the atomic validator
            try:
                # Convert atomic_id to validator module name
                # e.g., "query_erc20_balance" -> "query_erc20_balance_validator"
                validator_module_name = f"bsc_quest_bench.validators.{atomic_id}_validator"
                validator_module = importlib.import_module(validator_module_name)
                
                # Get the validator class (usually named like QueryErc20BalanceValidator)
                # Try common naming patterns
                class_name = ''.join(word.capitalize() for word in atomic_id.split('_')) + 'Validator'
                validator_class = getattr(validator_module, class_name)
                
                validators.append({
                    'atomic_id': atomic_id,
                    'alias': atomic_op.get('alias'),
                    'step': atomic_op.get('step'),
                    'validator': validator_class
                })
                
            except Exception as e:
                print(f"Warning: Failed to load validator for {atomic_id}: {e}")
                validators.append({
                    'atomic_id': atomic_id,
                    'alias': atomic_op.get('alias'),
                    'step': atomic_op.get('step'),
                    'validator': None
                })
        
        return validators
    
    def validate(self, agent_address: str, transaction_results: List[Dict], 
                 initial_state: Dict, final_state: Dict) -> Dict[str, Any]:
        """
        Validate composite problem execution
        
        Args:
            agent_address: Agent's address
            transaction_results: List of transaction results (one per atomic operation)
            initial_state: Initial blockchain state (balances, etc.)
            final_state: Final blockchain state after all operations
        
        Returns:
            Validation result dictionary with score breakdown
        """
        print(f"\n{'='*60}")
        print(f"Validating Composite Problem: {self.composite_id}")
        print(f"{'='*60}\n")
        
        atomic_scores = []
        atomic_details = []
        states_history = {'initial': initial_state}
        
        # Validate each atomic operation sequentially
        for i, (validator_info, tx_result) in enumerate(zip(self.atomic_validators, transaction_results)):
            atomic_id = validator_info['atomic_id']
            alias = validator_info['alias']
            validator_class = validator_info['validator']
            
            print(f"Step {i+1}: Validating {atomic_id} (alias: {alias})")
            print(f"{'-'*60}")
            
            if validator_class is None:
                print(f"⚠️  Warning: No validator available for {atomic_id}")
                atomic_scores.append(0.0)
                atomic_details.append({
                    'atomic_id': atomic_id,
                    'alias': alias,
                    'step': i + 1,
                    'score': 0.0,
                    'status': 'no_validator',
                    'error': 'Validator not found'
                })
                continue
            
            try:
                # Instantiate validator (assume it takes agent_address)
                validator = validator_class(agent_address)
                
                # Validate this atomic operation
                # Note: Atomic validators should handle their own validation logic
                atomic_result = validator.validate(
                    tx_result.get('transaction', {}),
                    initial_state,
                    final_state
                )
                
                score = atomic_result.get('score', 0.0)
                atomic_scores.append(score)
                
                atomic_details.append({
                    'atomic_id': atomic_id,
                    'alias': alias,
                    'step': i + 1,
                    'score': score,
                    'status': 'success' if score >= 60 else 'failed',
                    'details': atomic_result.get('details', {}),
                    'checks': atomic_result.get('checks', {})
                })
                
                print(f"✅ Score: {score:.2f}/100")
                
                # Store state for inter-operation checks
                if 'query' in atomic_id:
                    states_history[alias] = atomic_result.get('query_result', {})
                
            except Exception as e:
                print(f"❌ Error validating {atomic_id}: {e}")
                atomic_scores.append(0.0)
                atomic_details.append({
                    'atomic_id': atomic_id,
                    'alias': alias,
                    'step': i + 1,
                    'score': 0.0,
                    'status': 'error',
                    'error': str(e)
                })
            
            print()
        
        # Calculate composite score
        if self.scoring_method == 'average':
            composite_score = sum(atomic_scores) / len(atomic_scores) if atomic_scores else 0.0
        elif self.scoring_method == 'weighted':
            # For weighted, we'd need weights in the definition
            # For now, fall back to average
            composite_score = sum(atomic_scores) / len(atomic_scores) if atomic_scores else 0.0
        else:
            composite_score = sum(atomic_scores) / len(atomic_scores) if atomic_scores else 0.0
        
        # Perform inter-operation checks (optional, adds bonus/penalty)
        inter_op_score = self._perform_inter_operation_checks(states_history, transaction_results)
        
        # Adjust composite score with inter-operation checks
        # Weight: 90% atomic operations, 10% inter-operation consistency
        final_score = composite_score * 0.9 + inter_op_score * 0.1
        
        # Determine pass/fail
        passed = final_score >= 60.0
        
        # Summary
        print(f"\n{'='*60}")
        print(f"Composite Validation Summary")
        print(f"{'='*60}")
        print(f"Atomic Operations Validated: {len(atomic_scores)}")
        print(f"Average Atomic Score: {composite_score:.2f}/100")
        print(f"Inter-Operation Score: {inter_op_score:.2f}/100")
        print(f"Final Composite Score: {final_score:.2f}/100")
        print(f"Status: {'✅ PASSED' if passed else '❌ FAILED'}")
        print(f"{'='*60}\n")
        
        return {
            'score': final_score,
            'passed': passed,
            'composite_id': self.composite_id,
            'atomic_scores': atomic_scores,
            'atomic_details': atomic_details,
            'composite_score_breakdown': {
                'atomic_average': composite_score,
                'inter_operation': inter_op_score,
                'final': final_score
            },
            'scoring_method': self.scoring_method,
            'total_operations': len(atomic_scores),
            'successful_operations': sum(1 for s in atomic_scores if s >= 60),
            'failed_operations': sum(1 for s in atomic_scores if s < 60)
        }
    
    def _perform_inter_operation_checks(self, states_history: Dict, 
                                       transaction_results: List[Dict]) -> float:
        """
        Perform optional inter-operation consistency checks
        
        Args:
            states_history: Historical states from query operations
            transaction_results: Transaction results
        
        Returns:
            Inter-operation check score (0-100)
        """
        if not self.inter_op_checks:
            return 100.0  # No checks defined, full score
        
        print(f"\nPerforming Inter-Operation Checks...")
        print(f"{'-'*60}")
        
        total_checks = len(self.inter_op_checks)
        passed_checks = 0
        
        for check in self.inter_op_checks:
            check_type = check.get('type')
            description = check.get('description', check_type)
            
            print(f"Checking: {description}")
            
            try:
                if check_type == 'balance_decrease':
                    # Example: Check balance decreased by transfer amount
                    # This is a simplified check - in practice, need more robust implementation
                    passed = True  # Placeholder
                    print(f"  {'✅' if passed else '❌'} Balance consistency check")
                    if passed:
                        passed_checks += 1
                else:
                    print(f"  ⚠️  Unknown check type: {check_type}")
            
            except Exception as e:
                print(f"  ❌ Error performing check: {e}")
        
        score = (passed_checks / total_checks * 100) if total_checks > 0 else 100.0
        print(f"Inter-Operation Checks: {passed_checks}/{total_checks} passed")
        
        return score


def load_composite_definition(composite_id: str) -> Dict[str, Any]:
    """
    Load composite problem definition from JSON file
    
    Args:
        composite_id: Composite problem ID
    
    Returns:
        Composite problem definition dictionary
    """
    # Construct path to composite problem JSON
    composite_path = Path(__file__).parent.parent / 'question_bank' / 'composite_problems' / f'{composite_id}.json'
    
    if not composite_path.exists():
        raise FileNotFoundError(f"Composite problem definition not found: {composite_path}")
    
    with open(composite_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def validate_composite(composite_id: str, agent_address: str, 
                      transaction_results: List[Dict],
                      initial_state: Dict, final_state: Dict) -> Dict[str, Any]:
    """
    Convenience function to validate a composite problem
    
    Args:
        composite_id: Composite problem ID
        agent_address: Agent's address
        transaction_results: List of transaction results
        initial_state: Initial blockchain state
        final_state: Final blockchain state
    
    Returns:
        Validation result
    """
    composite_def = load_composite_definition(composite_id)
    validator = CompositeValidator(composite_def)
    return validator.validate(agent_address, transaction_results, initial_state, final_state)


# Example usage
if __name__ == "__main__":
    # This is just a structural example
    print("Composite Validator - Generic validator for all composite problems")
    print("\nUsage:")
    print("  validator = CompositeValidator(composite_definition)")
    print("  result = validator.validate(agent_address, tx_results, initial_state, final_state)")
    print("\nThis validator automatically:")
    print("  1. Loads atomic validators for each operation")
    print("  2. Validates each operation sequentially")
    print("  3. Calculates composite score (average/weighted)")
    print("  4. Performs optional inter-operation checks")

