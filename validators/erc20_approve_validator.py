"""
ERC20 Approve Validator

Validates that an ERC20 token approval transaction is correctly executed
"""

from typing import Dict, Any


class ERC20ApproveValidator:
    """Validator for ERC20 token approval transactions"""
    
    def __init__(self, token_address: str, spender_address: str, amount: float, token_decimals: int = 18):
        """
        Initialize validator
        
        Args:
            token_address: ERC20 token contract address
            spender_address: Address that is being approved to spend tokens
            amount: Expected approval amount in tokens (float)
            token_decimals: Token decimals (default: 18)
        """
        from decimal import Decimal
        
        self.expected_token = token_address.lower()
        self.expected_spender = spender_address.lower()
        # Convert token amount to smallest unit
        self.expected_amount = int(Decimal(str(amount)) * Decimal(10 ** token_decimals))
        self.token_decimals = token_decimals
        self.max_score = 100
    
    def validate(
        self,
        tx: Dict[str, Any],
        receipt: Dict[str, Any],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate the transaction execution results
        
        Args:
            tx: Transaction object
            receipt: Transaction receipt
            state_before: Blockchain state before transaction
            state_after: Blockchain state after transaction
            
        Returns:
            Validation results including score and details
        """
        score = 0
        details = {}
        checks = []
        
        # Check 1: Transaction success (30 points)
        tx_success = receipt.get('status') == 1
        if tx_success:
            score += 30
            checks.append({
                'name': 'Transaction Success',
                'passed': True,
                'points': 30,
                'message': 'Transaction executed successfully'
            })
        else:
            checks.append({
                'name': 'Transaction Success',
                'passed': False,
                'points': 0,
                'message': f"Transaction failed with status: {receipt.get('status')}"
            })
            return {
                'score': score,
                'max_score': self.max_score,
                'passed': False,
                'checks': checks,
                'details': details
            }
        
        # Check 2: Contract address correct (20 points)
        actual_to = tx.get('to', '').lower()
        contract_correct = actual_to == self.expected_token
        
        if contract_correct:
            score += 20
            checks.append({
                'name': 'Contract Address',
                'passed': True,
                'points': 20,
                'message': f'Correct token contract: {self.expected_token}'
            })
        else:
            checks.append({
                'name': 'Contract Address',
                'passed': False,
                'points': 0,
                'message': f'Expected: {self.expected_token}, Got: {actual_to}'
            })
        
        details['expected_token'] = self.expected_token
        details['actual_to'] = actual_to
        
        # Check 3: Function signature (20 points)
        # ERC20 approve function selector: 0x095ea7b3 (first 4 bytes of keccak256("approve(address,uint256)"))
        tx_data = tx.get('data', '0x')
        
        if tx_data and len(tx_data) >= 10:
            function_selector = tx_data[:10].lower()
            expected_selector = '0x095ea7b3'  # approve(address,uint256)
            
            if function_selector == expected_selector:
                score += 20
                checks.append({
                    'name': 'Function Signature',
                    'passed': True,
                    'points': 20,
                    'message': 'Correct ERC20 approve function signature'
                })
                
                # Decode parameters from data
                try:
                    if len(tx_data) >= 138:
                        spender_hex = tx_data[10:74]
                        amount_hex = tx_data[74:138]
                        
                        spender_address = '0x' + spender_hex[-40:]
                        amount_value = int(amount_hex, 16)
                        
                        details['decoded_spender'] = spender_address.lower()
                        details['decoded_amount'] = amount_value
                except Exception as e:
                    details['decode_error'] = str(e)
            else:
                checks.append({
                    'name': 'Function Signature',
                    'passed': False,
                    'points': 0,
                    'message': f'Expected: {expected_selector}, Got: {function_selector}'
                })
        else:
            checks.append({
                'name': 'Function Signature',
                'passed': False,
                'points': 0,
                'message': 'No data field or too short'
            })
        
        details['function_selector'] = tx_data[:10] if tx_data else None
        
        # Check 4: Allowance set correctly (30 points)
        # Check if allowance was set by examining state_after
        allowance_after = state_after.get('allowance', 0)
        
        # Allow small tolerance for potential issues
        tolerance = int(self.expected_amount * 0.001)  # 0.1% tolerance
        allowance_correct = abs(allowance_after - self.expected_amount) <= tolerance
        
        if allowance_correct:
            score += 30
            checks.append({
                'name': 'Allowance Set',
                'passed': True,
                'points': 30,
                'message': f'Allowance correctly set: {allowance_after} (expected: {self.expected_amount})'
            })
        else:
            checks.append({
                'name': 'Allowance Set',
                'passed': False,
                'points': 0,
                'message': f'Expected allowance: {self.expected_amount}, Got: {allowance_after}'
            })
        
        details['expected_spender'] = self.expected_spender
        details['expected_amount'] = self.expected_amount
        details['allowance_after'] = allowance_after
        
        # Final result
        passed = score >= self.max_score * 0.8  # 80% threshold
        
        return {
            'score': score,
            'max_score': self.max_score,
            'passed': passed,
            'checks': checks,
            'details': details
        }

