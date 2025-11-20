"""
ERC721 Safe Transfer Validator

验证 ERC721 NFT 的安全转账是否正确执行。
"""

from typing import Dict, Any


class ERC721SafeTransferValidator:
    """验证 ERC721 安全转账"""
    
    def __init__(
        self,
        nft_address: str,
        to_address: str,
        token_id: int
    ):
        self.nft_address = nft_address.lower()
        self.to_address = to_address.lower()
        self.token_id = token_id
        
        # safeTransferFrom(address,address,uint256) 函数选择器
        self.expected_selector = '0x42842e0e'
        
        # 满分 100 分
        self.max_score = 100
    
    def validate(
        self,
        tx: Dict[str, Any],
        receipt: Dict[str, Any],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证 ERC721 安全转账交易
        
        检查项：
        1. 交易成功执行
        2. NFT 所有权正确转移
        3. 使用了 safeTransferFrom 函数（正确的 selector）
        """
        checks = []
        total_score = 0
        
        # 1. 验证交易成功 (30 分)
        tx_status = receipt.get('status', 0)
        if tx_status == 1:
            checks.append({
                'name': 'Transaction Success',
                'passed': True,
                'message': 'Transaction executed successfully',
                'score': 30
            })
            total_score += 30
        else:
            checks.append({
                'name': 'Transaction Success',
                'passed': False,
                'message': f'Transaction failed with status: {tx_status}',
                'score': 30
            })
            # 如果交易失败，直接返回
            return {
                'passed': False,
                'score': 0,
                'max_score': self.max_score,
                'checks': checks,
                'details': {
                    'nft_address': self.nft_address,
                    'token_id': self.token_id,
                    'to_address': self.to_address,
                    'transaction_status': tx_status
                }
            }
        
        # 2. 验证 NFT 所有权转移 (40 分)
        owner_before = state_before.get('nft_owner', '').lower() if state_before.get('nft_owner') else None
        owner_after = state_after.get('nft_owner', '').lower() if state_after.get('nft_owner') else None
        
        if owner_after and owner_after == self.to_address:
            checks.append({
                'name': 'NFT Ownership Transfer',
                'passed': True,
                'message': f'NFT #{self.token_id} correctly transferred to {self.to_address}',
                'score': 40,
                'details': {
                    'owner_before': owner_before,
                    'owner_after': owner_after,
                    'expected': self.to_address
                }
            })
            total_score += 40
        else:
            checks.append({
                'name': 'NFT Ownership Transfer',
                'passed': False,
                'message': f'NFT ownership not transferred correctly. Expected: {self.to_address}, Got: {owner_after}',
                'score': 40,
                'details': {
                    'owner_before': owner_before,
                    'owner_after': owner_after,
                    'expected': self.to_address
                }
            })
        
        # 3. 验证使用了正确的函数 selector (30 分)
        tx_data = tx.get('data', '') or tx.get('input', '')
        
        if isinstance(tx_data, bytes):
            tx_data = tx_data.hex()
        if isinstance(tx_data, str) and tx_data.startswith('0x'):
            tx_data = tx_data[2:]
        
        # 提取函数 selector (前 4 字节 = 8 个十六进制字符)
        if len(tx_data) >= 8:
            actual_selector = '0x' + tx_data[:8]
            
            if actual_selector.lower() == self.expected_selector.lower():
                checks.append({
                    'name': 'Function Selector',
                    'passed': True,
                    'message': f'Correct safeTransferFrom selector: {actual_selector}',
                    'score': 30,
                    'details': {
                        'expected': self.expected_selector,
                        'actual': actual_selector
                    }
                })
                total_score += 30
            else:
                checks.append({
                    'name': 'Function Selector',
                    'passed': False,
                    'message': f'Incorrect function selector. Expected safeTransferFrom ({self.expected_selector}), got {actual_selector}',
                    'score': 30,
                    'details': {
                        'expected': self.expected_selector,
                        'actual': actual_selector,
                        'note': 'Should use safeTransferFrom(address,address,uint256), not transferFrom'
                    }
                })
        else:
            checks.append({
                'name': 'Function Selector',
                'passed': False,
                'message': 'Transaction data too short or missing',
                'score': 30
            })
        
        # 汇总结果
        all_passed = all(check['passed'] for check in checks)
        
        return {
            'passed': all_passed,
            'score': total_score,
            'max_score': self.max_score,
            'checks': checks,
            'details': {
                'nft_address': self.nft_address,
                'token_id': self.token_id,
                'expected_recipient': self.to_address,
                'owner_before': owner_before,
                'owner_after': owner_after,
                'expected_selector': self.expected_selector,
                'actual_selector': actual_selector if len(tx_data) >= 8 else 'N/A'
            }
        }

