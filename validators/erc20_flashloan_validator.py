"""
ERC20 FlashLoan Validator

验证闪电贷操作。
"""

from typing import Dict, Any


class ERC20FlashLoanValidator:
    """验证 ERC20 闪电贷操作"""
    
    def __init__(
        self,
        flashloan_contract_address: str,
        token_address: str,
        amount: float,
        token_decimals: int,
        fee_percentage: float
    ):
        self.flashloan_contract = flashloan_contract_address.lower()
        self.token_address = token_address.lower()
        self.amount = amount
        self.token_decimals = token_decimals
        self.fee_percentage = fee_percentage
        
        # 计算费用（单位：token smallest unit）
        amount_smallest = int(amount * (10 ** token_decimals))
        self.expected_fee = int(amount_smallest * fee_percentage / 100)
        
        self.max_score = 100
    
    def validate(
        self,
        tx: Dict[str, Any],
        receipt: Dict[str, Any],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证闪电贷交易
        
        Args:
            tx: 交易对象
            receipt: 交易收据
            state_before: 交易前状态
            state_after: 交易后状态
            
        Returns:
            验证结果字典
        
        检查项：
        1. 交易成功执行 (30%)
        2. 调用了正确的闪电贷合约 (20%)
        3. 使用了 executeFlashLoan 函数 (20%)
        4. 支付了正确的费用 (30%)
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
                    'flashloan_contract': self.flashloan_contract,
                    'token_address': self.token_address,
                    'amount': self.amount,
                    'expected_fee': self.expected_fee / (10 ** self.token_decimals),
                    'transaction_status': tx_status
                }
            }
        
        # 2. 验证调用了正确的闪电贷合约 (20 分)
        tx_to = tx.get('to', '').lower()
        if tx_to == self.flashloan_contract:
            results.append({
                'check': 'Contract Address',
                'passed': True,
                'message': f'Correct flash loan contract: {tx_to}',
                'weight': 0.2
            })
            total_score += 20
        else:
            results.append({
                'check': 'Contract Address',
                'passed': False,
                'message': f'Wrong contract. Expected: {self.flashloan_contract}, Got: {tx_to}',
                'weight': 0.2
            })
        
        # 3. 验证使用了 executeFlashLoan 函数 (20 分)
        tx_data = tx.get('data', '') or tx.get('input', '')
        
        if isinstance(tx_data, bytes):
            tx_data = tx_data.hex()
        if isinstance(tx_data, str) and tx_data.startswith('0x'):
            tx_data = tx_data[2:]
        
        # executeFlashLoan(address,uint256) 函数选择器
        # keccak256("executeFlashLoan(address,uint256)") 的前 4 字节
        expected_selector = '0x6065c245'
        actual_selector = 'N/A'
        
        if len(tx_data) >= 8:
            actual_selector = '0x' + tx_data[:8]
            
            if actual_selector.lower() == expected_selector.lower():
                results.append({
                    'check': 'Function Signature',
                    'passed': True,
                    'message': f'Correct executeFlashLoan selector: {actual_selector}',
                    'weight': 0.2,
                    'details': {
                        'expected': expected_selector,
                        'actual': actual_selector
                    }
                })
                total_score += 20
            else:
                results.append({
                    'check': 'Function Signature',
                    'passed': False,
                    'message': f'Incorrect function selector. Expected executeFlashLoan ({expected_selector}), got {actual_selector}',
                    'weight': 0.2,
                    'details': {
                        'expected': expected_selector,
                        'actual': actual_selector
                    }
                })
        else:
            results.append({
                'check': 'Function Signature',
                'passed': False,
                'message': 'Transaction data too short or missing',
                'weight': 0.2
            })
        
        # 4. 验证费用支付 (30 分)
        # 闪电贷会导致用户余额减少费用金额
        balance_before = state_before.get('token_balance', 0)
        balance_after = state_after.get('token_balance', 0)
        
        balance_decrease = balance_before - balance_after
        
        # 允许一些误差（由于精度问题）
        fee_tolerance = max(1, self.expected_fee // 100)  # 1% tolerance
        
        fee_check_passed = abs(balance_decrease - self.expected_fee) <= fee_tolerance
        
        if fee_check_passed:
            results.append({
                'check': 'Fee Payment',
                'passed': True,
                'message': f'Flash loan fee paid correctly: {balance_decrease / (10 ** self.token_decimals):.6f} tokens',
                'weight': 0.3,
                'details': {
                    'balance_before': balance_before / (10 ** self.token_decimals),
                    'balance_after': balance_after / (10 ** self.token_decimals),
                    'balance_decrease': balance_decrease / (10 ** self.token_decimals),
                    'expected_fee': self.expected_fee / (10 ** self.token_decimals),
                    'fee_percentage': self.fee_percentage
                }
            })
            total_score += 30
        else:
            results.append({
                'check': 'Fee Payment',
                'passed': False,
                'message': f'Fee mismatch. Expected: {self.expected_fee / (10 ** self.token_decimals):.6f}, Actual: {balance_decrease / (10 ** self.token_decimals):.6f}',
                'weight': 0.3,
                'details': {
                    'balance_before': balance_before / (10 ** self.token_decimals),
                    'balance_after': balance_after / (10 ** self.token_decimals),
                    'balance_decrease': balance_decrease / (10 ** self.token_decimals),
                    'expected_fee': self.expected_fee / (10 ** self.token_decimals),
                    'fee_percentage': self.fee_percentage
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
                'flashloan_contract': self.flashloan_contract,
                'token_address': self.token_address,
                'amount': self.amount,
                'expected_fee': self.expected_fee / (10 ** self.token_decimals),
                'balance_before': balance_before / (10 ** self.token_decimals),
                'balance_after': balance_after / (10 ** self.token_decimals),
                'balance_decrease': balance_decrease / (10 ** self.token_decimals),
                'actual_selector': actual_selector
            }
        }

