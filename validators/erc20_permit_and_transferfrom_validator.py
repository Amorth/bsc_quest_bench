"""
ERC20 Permit and TransferFrom Validator (EIP-2612)

验证使用 EIP-2612 permit 功能进行授权，然后执行 transferFrom 的操作。
"""

from typing import Dict, Any
from decimal import Decimal


class ERC20PermitAndTransferFromValidator:
    """验证 EIP-2612 permit + transferFrom 操作"""
    
    def __init__(
        self,
        token_address: str,
        owner_address: str,
        to_address: str,
        amount: float,
        token_decimals: int = 18
    ):
        self.token_address = token_address.lower()
        self.owner_address = owner_address.lower()
        self.to_address = to_address.lower()
        
        # 使用 Decimal 精确计算
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
        验证 EIP-2612 permit + transferFrom 交易
        
        Args:
            tx: 交易对象
            receipt: 交易收据
            state_before: 交易前状态
            state_after: 交易后状态
            
        Returns:
            验证结果字典
        
        检查项：
        1. 交易成功执行 (30%)
        2. Owner 代币余额正确减少 (35%)
        3. Recipient 代币余额正确增加 (35%)
        
        注意：此验证器关注最终结果（余额变化），而不是具体实现方式
        （可以是 permit+transferFrom 两个交易，或者预先 permit 再 transferFrom）
        """
        
        results = []
        total_score = 0
        
        # 1. 验证交易成功 (30 分)
        tx_status = receipt.get('status', 0)
        if tx_status == 1:
            results.append({
                'check': 'Transaction Success',
                'passed': True,
                'message': 'Transaction executed successfully',
                'weight': 0.3
            })
            total_score += 30
        else:
            results.append({
                'check': 'Transaction Success',
                'passed': False,
                'message': f'Transaction failed with status: {tx_status}',
                'weight': 0.3
            })
            # 如果交易失败，直接返回
            return {
                'passed': False,
                'score': 0,
                'max_score': self.max_score,
                'checks': results,
                'details': {
                    'token_address': self.token_address,
                    'owner_address': self.owner_address,
                    'to_address': self.to_address,
                    'expected_amount': self.expected_amount,
                    'transaction_status': tx_status
                }
            }
        
        # 2. 验证 owner 代币余额减少 (35 分)
        owner_balance_before = state_before.get('token_balance', 0)
        owner_balance_after = state_after.get('token_balance', 0)
        actual_decrease = owner_balance_before - owner_balance_after
        
        if actual_decrease == self.expected_amount:
            results.append({
                'check': 'Owner Token Balance Decrease',
                'passed': True,
                'message': f'Owner balance correctly decreased by {self.expected_amount} units',
                'weight': 0.35,
                'details': {
                    'balance_before': owner_balance_before,
                    'balance_after': owner_balance_after,
                    'actual_decrease': actual_decrease,
                    'expected_decrease': self.expected_amount
                }
            })
            total_score += 35
        else:
            results.append({
                'check': 'Owner Token Balance Decrease',
                'passed': False,
                'message': f'Balance decrease mismatch. Expected: {self.expected_amount}, Got: {actual_decrease}',
                'weight': 0.35,
                'details': {
                    'balance_before': owner_balance_before,
                    'balance_after': owner_balance_after,
                    'actual_decrease': actual_decrease,
                    'expected_decrease': self.expected_amount
                }
            })
        
        # 3. 验证 recipient 代币余额增加 (35 分)
        recipient_balance_before = state_before.get('target_token_balance', 0)
        recipient_balance_after = state_after.get('target_token_balance', 0)
        actual_increase = recipient_balance_after - recipient_balance_before
        
        if actual_increase == self.expected_amount:
            results.append({
                'check': 'Recipient Token Balance Increase',
                'passed': True,
                'message': f'Recipient balance correctly increased by {self.expected_amount} units',
                'weight': 0.35,
                'details': {
                    'balance_before': recipient_balance_before,
                    'balance_after': recipient_balance_after,
                    'actual_increase': actual_increase,
                    'expected_increase': self.expected_amount
                }
            })
            total_score += 35
        else:
            results.append({
                'check': 'Recipient Token Balance Increase',
                'passed': False,
                'message': f'Balance increase mismatch. Expected: {self.expected_amount}, Got: {actual_increase}',
                'weight': 0.35,
                'details': {
                    'balance_before': recipient_balance_before,
                    'balance_after': recipient_balance_after,
                    'actual_increase': actual_increase,
                    'expected_increase': self.expected_amount
                }
            })
        
        # 汇总结果
        all_passed = all(check['passed'] for check in results)
        
        return {
            'passed': all_passed,
            'score': total_score,
            'max_score': self.max_score,
            'checks': results,
            'details': {
                'token_address': self.token_address,
                'owner_address': self.owner_address,
                'to_address': self.to_address,
                'expected_amount': self.expected_amount,
                'owner_balance_before': owner_balance_before,
                'owner_balance_after': owner_balance_after,
                'recipient_balance_before': recipient_balance_before,
                'recipient_balance_after': recipient_balance_after
            }
        }

