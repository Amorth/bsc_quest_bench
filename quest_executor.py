"""
BSC Quest Executor - 执行层

负责:
1. 执行 TypeScript 生成的交易
2. 获取交易执行结果和 receipt
3. 调用验证器进行验证
4. 返回评分结果
"""

import subprocess
import json
import base64
import tempfile
import os
from typing import Dict, Any, Optional
from web3 import Web3
from eth_account import Account


class QuestExecutor:
    """Quest 执行器"""
    
    def __init__(self, w3: Web3, private_key: str):
        """
        初始化执行器
        
        Args:
            w3: Web3 实例
            private_key: 测试账户私钥
        """
        self.w3 = w3
        self.private_key = private_key
        self.account = Account.from_key(private_key)
        self.address = self.account.address
    
    def execute_transaction(
        self,
        tx: Dict[str, Any],
        validator=None,
        token_address: str = None,
        target_address_for_token: str = None,
        spender_address: str = None,
        nft_address: str = None,
        nft_token_id: int = None,
        operator_address: str = None,
        nft_type: str = None,
        counter_contract_address: str = None,
        message_board_contract_address: str = None,
        proxy_address: str = None,
        implementation_address: str = None,
        expected_value: int = None
    ) -> Dict[str, Any]:
        """
        执行交易并进行验证
        
        Args:
            tx: 交易对象
            validator: 验证器实例
            token_address: ERC20 token 地址（可选，用于查询 token 余额）
            target_address_for_token: 目标地址（用于查询其 token 余额）
            spender_address: 被授权地址（用于查询 allowance）
            counter_contract_address: SimpleCounter 合约地址（用于查询 counter 值）
            message_board_contract_address: MessageBoard 合约地址（用于查询 message 值）
            
        Returns:
            包含交易结果和验证结果的字典
        """
        print("="*80)
        print("⚙️  开始执行交易...")
        print("="*80)
        
        # 获取目标地址（如果有）
        target_address = tx.get('to')
        
        # 获取交易前状态（包括目标地址状态和 token 余额）
        state_before = self._get_state_snapshot(
            target_address,
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
            implementation_address=implementation_address
        )
        # 添加 expected_value 到 state_before
        if expected_value is not None:
            state_before['expected_value'] = expected_value
        if proxy_address is not None:
            state_before['proxy_address'] = proxy_address.lower()
        
        try:
            # 1. 准备交易
            transaction = self._prepare_transaction(tx)
            
            # 2. 签名交易
            signed_txn = self.w3.eth.account.sign_transaction(
                transaction,
                self.private_key
            )
            
            # 3. 发送交易
            raw_tx = getattr(signed_txn, 'rawTransaction', None) or getattr(signed_txn, 'raw_transaction', None)
            if raw_tx is None:
                raise AttributeError("无法获取签名后的交易数据")
            
            tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
            print(f"✅ 交易已发送: {tx_hash.hex()}")
            
            # 4. 等待确认
            print(f"⛏️  等待交易确认...")
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            print(f"✅ 交易已确认")
            print(f"   Block: {receipt['blockNumber']}")
            print(f"   Gas Used: {receipt['gasUsed']}")
            print(f"   Status: {'成功' if receipt['status'] == 1 else '失败'}")
            
            # 5. 获取交易后状态（包括目标地址状态和 token 余额）
            state_after = self._get_state_snapshot(
                target_address,
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
                implementation_address=implementation_address
            )
            
            # 6. 转换 receipt 为标准格式
            receipt_dict = self._convert_receipt(receipt)
            
            # 7. 验证 (如果提供了验证器)
            validation_result = None
            if validator:
                print("\n" + "="*80)
                print("🔍 开始验证...")
                print("="*80)
                validation_result = validator.validate(
                    tx=transaction,
                    receipt=receipt_dict,
                    state_before=state_before,
                    state_after=state_after
                )
                
                # 打印验证结果
                self._print_validation_result(validation_result)
            
            return {
                'success': True,
                'tx_hash': tx_hash.hex(),
                'receipt': receipt_dict,
                'state_before': state_before,
                'state_after': state_after,
                'validation': validation_result
            }
            
        except Exception as e:
            print(f"\n❌ 交易执行失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'state_before': state_before
            }
    
    def _prepare_transaction(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        """
        准备交易对象
        
        Args:
            tx: 原始交易对象
            
        Returns:
            准备好的交易对象
        """
        from eth_utils import to_checksum_address
        
        # 获取链 ID
        chain_id = self.w3.eth.chain_id
        
        transaction = {
            'from': to_checksum_address(self.address),
            'to': to_checksum_address(tx['to']) if tx.get('to') else None,
            'value': int(tx.get('value', 0)),
            'gas': int(tx.get('gasLimit', tx.get('gas', 500000))),  # 支持 gasLimit 或 gas
            'nonce': self.w3.eth.get_transaction_count(self.address),
            'chainId': chain_id,  # 添加 chainId
        }
        
        # 处理 gas price
        tx_type = tx.get('type', 0)
        if tx_type == 2:
            # EIP-1559
            transaction['maxPriorityFeePerGas'] = int(tx.get('maxPriorityFeePerGas', 10**9))
            transaction['maxFeePerGas'] = int(tx.get('maxFeePerGas', 2 * 10**9))
            transaction['type'] = 2
        else:
            # Legacy
            transaction['gasPrice'] = int(tx.get('gasPrice', 10**9))
        
        # 处理 data
        if 'data' in tx and tx['data']:
            transaction['data'] = tx['data']
        
        return transaction
    
    def _get_state_snapshot(
        self,
        target_address: str = None,
        token_address: str = None,
        target_address_for_token: str = None,
        spender_address: str = None,
        nft_address: str = None,
        nft_token_id: int = None,
        operator_address: str = None,
        nft_type: str = None,
        counter_contract_address: str = None,
        message_board_contract_address: str = None,
        proxy_address: str = None,
        implementation_address: str = None
    ) -> Dict[str, Any]:
        """
        获取当前链上状态快照
        
        Args:
            target_address: 目标地址（可选），如果提供则获取目标地址的状态
            counter_contract_address: SimpleCounter 合约地址（可选），如果提供则获取 counter 值
            message_board_contract_address: MessageBoard 合约地址（可选），如果提供则获取 message 值
        
        Returns:
            状态快照字典
        """
        snapshot = {
            'block_number': self.w3.eth.block_number,
            'balance': self.w3.eth.get_balance(self.address),
            'nonce': self.w3.eth.get_transaction_count(self.address),
        }
        
        # 如果提供了目标地址，获取目标地址的状态
        if target_address:
            from eth_utils import to_checksum_address
            import time
            
            target_addr = to_checksum_address(target_address)
            
            # 获取目标地址的余额
            snapshot['target_balance'] = self.w3.eth.get_balance(target_addr)
            
            # 获取目标地址的代码大小（判断是否为合约）
            # 多次尝试获取代码，触发 Anvil 从远程拉取
            code = None
            for attempt in range(3):
                try:
                    code = self.w3.eth.get_code(target_addr)
                    code_len = len(code) if code else 0
                    
                    if attempt == 0:
                        print(f"🔍 Checking contract code for {target_addr[:10]}... (attempt {attempt + 1})")
                        print(f"   Code length: {code_len} bytes")
                    
                    if code and code_len > 2:
                        # 成功获取到合约代码
                        print(f"   ✅ Contract code found: {code_len} bytes")
                        break
                    
                    # 如果第一次没获取到，尝试额外的 RPC 调用来触发数据拉取
                    if attempt < 2:
                        print(f"   ⚠️  No code found, trying to trigger data fetch...")
                        # 尝试获取 storage，可能触发合约数据加载
                        try:
                            storage = self.w3.eth.get_storage_at(target_addr, 0)
                            print(f"   Storage at slot 0: {storage.hex()[:20]}...")
                        except Exception as se:
                            print(f"   Storage fetch error: {se}")
                        # 再次尝试获取余额
                        bal = self.w3.eth.get_balance(target_addr)
                        print(f"   Balance: {bal} wei")
                        time.sleep(0.2)  # 稍长的等待
                except Exception as e:
                    print(f"   ❌ Error getting code (attempt {attempt + 1}): {e}")
                    if attempt < 2:
                        time.sleep(0.2)
            
            final_code_size = len(code) if code and len(code) > 2 else 0
            snapshot['contract_code_size'] = final_code_size
            
            if final_code_size == 0:
                print(f"   ⚠️  WARNING: Final contract code size is 0 for {target_addr}")
        
        # 如果提供了 token 地址，获取 token 余额
        if token_address:
            from eth_utils import to_checksum_address
            
            token_addr = to_checksum_address(token_address)
            agent_addr = to_checksum_address(self.address)
            
            # 获取 agent 的 token 余额
            try:
                # ERC20 balanceOf function selector: 0x70a08231
                # balanceOf(address) -> uint256
                data = '0x70a08231' + '000000000000000000000000' + agent_addr[2:]
                result = self.w3.eth.call({
                    'to': token_addr,
                    'data': data
                })
                snapshot['token_balance'] = int(result.hex(), 16)
                print(f"📊 Token balance (agent): {snapshot['token_balance']} ({snapshot['token_balance'] / 10**18:.6f})")
            except Exception as e:
                print(f"⚠️  Error getting agent token balance: {e}")
                snapshot['token_balance'] = 0
            
            # 如果提供了目标地址，获取目标地址的 token 余额
            if target_address_for_token:
                target_token_addr = to_checksum_address(target_address_for_token)
                try:
                    data = '0x70a08231' + '000000000000000000000000' + target_token_addr[2:]
                    result = self.w3.eth.call({
                        'to': token_addr,
                        'data': data
                    })
                    snapshot['target_token_balance'] = int(result.hex(), 16)
                    print(f"📊 Token balance (target): {snapshot['target_token_balance']} ({snapshot['target_token_balance'] / 10**18:.6f})")
                except Exception as e:
                    print(f"⚠️  Error getting target token balance: {e}")
                    snapshot['target_token_balance'] = 0
            
            # 如果提供了 spender 地址，获取 allowance
            if spender_address:
                spender_addr = to_checksum_address(spender_address)
                try:
                    # ERC20 allowance function selector: 0xdd62ed3e
                    # allowance(address owner, address spender) -> uint256
                    # Encode: owner (32 bytes) + spender (32 bytes)
                    data = '0xdd62ed3e' + '000000000000000000000000' + agent_addr[2:] + '000000000000000000000000' + spender_addr[2:]
                    result = self.w3.eth.call({
                        'to': token_addr,
                        'data': data
                    })
                    snapshot['allowance'] = int(result.hex(), 16)
                    print(f"📊 Allowance (spender: {spender_addr[:10]}...): {snapshot['allowance']} ({snapshot['allowance'] / 10**18:.6f})")
                except Exception as e:
                    print(f"⚠️  Error getting allowance: {e}")
                    snapshot['allowance'] = 0
        
        # ERC721: 如果是 ERC721 类型，获取 NFT 所有者和批准地址
        if nft_address and nft_token_id is not None and nft_type == 'erc721':
            from eth_utils import to_checksum_address
            
            nft_addr = to_checksum_address(nft_address)
            
            try:
                # ERC721 ownerOf function selector: 0x6352211e
                # ownerOf(uint256 tokenId) -> address
                # Encode: tokenId (32 bytes)
                token_id_hex = format(nft_token_id, '064x')  # 64 hex chars = 32 bytes
                data = '0x6352211e' + token_id_hex
                result = self.w3.eth.call({
                    'to': nft_addr,
                    'data': data
                })
                # Extract address from result (last 20 bytes)
                owner_hex = result.hex()
                if len(owner_hex) >= 42:  # 0x + 40 hex chars
                    owner_address = '0x' + owner_hex[-40:]
                    snapshot['nft_owner'] = owner_address
                    print(f"📊 NFT #{nft_token_id} owner: {owner_address}")
                else:
                    snapshot['nft_owner'] = None
                    print(f"⚠️  Could not parse NFT owner from result: {owner_hex}")
            except Exception as e:
                print(f"⚠️  Error getting NFT owner: {e}")
                snapshot['nft_owner'] = None
            
            # 同时获取 NFT 的批准地址（getApproved）
            try:
                # ERC721 getApproved function selector: 0x081812fc
                # getApproved(uint256 tokenId) -> address
                # Encode: tokenId (32 bytes)
                token_id_hex = format(nft_token_id, '064x')  # 64 hex chars = 32 bytes
                data = '0x081812fc' + token_id_hex
                result = self.w3.eth.call({
                    'to': nft_addr,
                    'data': data
                })
                # Extract address from result (last 20 bytes)
                approved_hex = result.hex()
                if len(approved_hex) >= 42:  # 0x + 40 hex chars
                    approved_address = '0x' + approved_hex[-40:]
                    # 检查是否为零地址（没有批准）
                    if approved_address == '0x' + '0' * 40:
                        snapshot['nft_approved'] = None
                        print(f"📊 NFT #{nft_token_id} approved: None (zero address)")
                    else:
                        snapshot['nft_approved'] = approved_address
                        print(f"📊 NFT #{nft_token_id} approved: {approved_address}")
                else:
                    snapshot['nft_approved'] = None
                    print(f"⚠️  Could not parse NFT approved address from result: {approved_hex}")
            except Exception as e:
                print(f"⚠️  Error getting NFT approved address: {e}")
                snapshot['nft_approved'] = None
        
        # 如果提供了 NFT 地址和 operator 地址，查询 isApprovedForAll 状态
        if nft_address and operator_address:
            from eth_utils import to_checksum_address
            from eth_abi import encode
            
            nft_addr = to_checksum_address(nft_address)
            operator_addr = to_checksum_address(operator_address)
            agent_addr = to_checksum_address(self.address)
            
            try:
                # ERC721 isApprovedForAll function selector: 0xe985e9c5
                # isApprovedForAll(address owner, address operator) -> bool
                # Encode: owner (32 bytes) + operator (32 bytes)
                params = encode(['address', 'address'], [agent_addr, operator_addr])
                data = '0xe985e9c5' + params.hex()
                
                result = self.w3.eth.call({
                    'to': nft_addr,
                    'data': data
                })
                
                # Extract boolean from result (32 bytes)
                result_hex = result.hex()
                # Boolean is in the last byte, 0x01 = true, 0x00 = false
                if len(result_hex) >= 2:
                    # Remove '0x' prefix and get last byte
                    is_approved = int(result_hex[-1]) == 1 if result_hex[-1] in ['0', '1'] else int(result_hex[-2:], 16) > 0
                    snapshot['is_approved_for_all'] = is_approved
                    print(f"📊 isApprovedForAll (operator: {operator_addr[:10]}...): {is_approved}")
                else:
                    snapshot['is_approved_for_all'] = False
                    print(f"⚠️  Could not parse isApprovedForAll result: {result_hex}")
            except Exception as e:
                print(f"⚠️  Error getting isApprovedForAll status: {e}")
                snapshot['is_approved_for_all'] = False
        
        # ERC1155: 如果是 ERC1155 类型，查询余额
        # ERC1155 使用 balanceOf(address, uint256) 而不是 ownerOf(uint256)
        if nft_address and nft_token_id is not None and nft_type == 'erc1155':
            from eth_utils import to_checksum_address
            from eth_abi import encode
            
            nft_addr = to_checksum_address(nft_address)
            agent_addr = to_checksum_address(self.address)
            
            try:
                # ERC1155 balanceOf function selector: 0x00fdd58e
                # balanceOf(address account, uint256 id) -> uint256
                params = encode(['address', 'uint256'], [agent_addr, nft_token_id])
                data = '0x00fdd58e' + params.hex()
                
                result = self.w3.eth.call({
                    'to': nft_addr,
                    'data': data
                })
                
                # Extract balance from result (uint256)
                balance = int(result.hex(), 16)
                snapshot['erc1155_balance'] = balance
                print(f"📊 ERC1155 balance (agent, token #{nft_token_id}): {balance}")
            except Exception as e:
                # 如果失败，可能不是 ERC1155 代币（可能是 ERC721）
                # 或者可能是查询失败
                print(f"⚠️  Error getting ERC1155 balance (agent): {e}")
                snapshot['erc1155_balance'] = 0
            
            # 如果提供了目标地址，查询目标地址的 ERC1155 余额
            if target_address_for_token:
                target_addr = to_checksum_address(target_address_for_token)
                try:
                    params = encode(['address', 'uint256'], [target_addr, nft_token_id])
                    data = '0x00fdd58e' + params.hex()
                    
                    result = self.w3.eth.call({
                        'to': nft_addr,
                        'data': data
                    })
                    
                    balance = int(result.hex(), 16)
                    snapshot['target_erc1155_balance'] = balance
                    print(f"📊 ERC1155 balance (target, token #{nft_token_id}): {balance}")
                except Exception as e:
                    print(f"⚠️  Error getting ERC1155 balance (target): {e}")
                    snapshot['target_erc1155_balance'] = 0
        
        # SimpleCounter: 如果提供了 counter 合约地址，获取 counter 值
        if counter_contract_address:
            from eth_utils import to_checksum_address
            
            counter_addr = to_checksum_address(counter_contract_address)
            
            try:
                # SimpleCounter getCounter function selector: 0x8ada066e
                # getCounter() -> uint256
                data = '0x8ada066e'
                result = self.w3.eth.call({
                    'to': counter_addr,
                    'data': data
                })
                counter_value = int(result.hex(), 16)
                snapshot['counter_value'] = counter_value
                print(f"📊 Counter value: {counter_value}")
            except Exception as e:
                print(f"⚠️  Error getting counter value: {e}")
                snapshot['counter_value'] = 0
        
        # MessageBoard: 如果提供了 message board 合约地址，获取 message 值
        if message_board_contract_address:
            from eth_utils import to_checksum_address
            
            message_addr = to_checksum_address(message_board_contract_address)
            
            try:
                # MessageBoard getMessage function selector: 0xce6d41de
                # getMessage() -> string
                data = '0xce6d41de'
                result = self.w3.eth.call({
                    'to': message_addr,
                    'data': data
                })
                
                # Decode string from ABI encoded data
                # Skip first 32 bytes (offset), next 32 bytes is length, then the string
                if len(result) > 64:
                    # Offset is at bytes 0-32, length is at bytes 32-64
                    length = int.from_bytes(result[32:64], 'big')
                    # String data starts at byte 64
                    string_bytes = result[64:64+length]
                    message_value = string_bytes.decode('utf-8', errors='ignore')
                    snapshot['message_value'] = message_value
                    print(f"📊 Message value: \"{message_value}\"")
                else:
                    snapshot['message_value'] = ''
                    print(f"📊 Message value: (empty)")
            except Exception as e:
                print(f"⚠️  Error getting message value: {e}")
                snapshot['message_value'] = ''
        
        # DelegateCall: 如果提供了 proxy 和 implementation 地址，获取它们的值
        if proxy_address and implementation_address:
            from eth_utils import to_checksum_address
            
            proxy_addr = to_checksum_address(proxy_address)
            impl_addr = to_checksum_address(implementation_address)
            
            # getValue function selector: 0x20965255
            # getValue() -> uint256
            data = '0x20965255'
            
            # 查询 proxy 的值
            try:
                result = self.w3.eth.call({
                    'to': proxy_addr,
                    'data': data
                })
                proxy_value = int(result.hex(), 16)
                snapshot['proxy_value'] = proxy_value
                print(f"📊 Proxy value: {proxy_value}")
            except Exception as e:
                print(f"⚠️  Error getting proxy value: {e}")
                snapshot['proxy_value'] = 0
            
            # 查询 implementation 的值
            try:
                result = self.w3.eth.call({
                    'to': impl_addr,
                    'data': data
                })
                impl_value = int(result.hex(), 16)
                snapshot['implementation_value'] = impl_value
                print(f"📊 Implementation value: {impl_value}")
            except Exception as e:
                print(f"⚠️  Error getting implementation value: {e}")
                snapshot['implementation_value'] = 0
        
        return snapshot
    
    def _convert_receipt(self, receipt) -> Dict[str, Any]:
        """
        转换 receipt 为标准字典格式
        
        Args:
            receipt: Web3 receipt 对象
            
        Returns:
            标准格式的 receipt 字典
        """
        receipt_dict = {
            'transactionHash': receipt['transactionHash'].hex() if isinstance(receipt['transactionHash'], bytes) else receipt['transactionHash'],
            'blockHash': receipt['blockHash'].hex() if isinstance(receipt['blockHash'], bytes) else receipt['blockHash'],
            'blockNumber': receipt['blockNumber'],
            'from': receipt['from'],
            'to': receipt['to'],
            'gasUsed': receipt['gasUsed'],
            'cumulativeGasUsed': receipt.get('cumulativeGasUsed', receipt['gasUsed']),
            'contractAddress': receipt.get('contractAddress'),
            'status': receipt['status'],
            'logsBloom': receipt.get('logsBloom', '0x' + '0' * 512),
            'type': receipt.get('type', '0x0'),
            'effectiveGasPrice': receipt.get('effectiveGasPrice', 0),
            'transactionIndex': receipt.get('transactionIndex', 0),
        }
        
        # 转换 logs
        if receipt.get('logs'):
            converted_logs = []
            for log in receipt['logs']:
                converted_log = {
                    'address': log['address'],
                    'topics': [t.hex() if isinstance(t, bytes) else t for t in log['topics']],
                    'data': log['data'],
                    'blockNumber': log['blockNumber'],
                    'transactionHash': log['transactionHash'].hex() if isinstance(log['transactionHash'], bytes) else log['transactionHash'],
                    'transactionIndex': log.get('transactionIndex', 0),
                    'blockHash': log['blockHash'].hex() if isinstance(log['blockHash'], bytes) else log['blockHash'],
                    'logIndex': log.get('logIndex', 0),
                    'removed': log.get('removed', False),
                }
                converted_logs.append(converted_log)
            receipt_dict['logs'] = converted_logs
        else:
            receipt_dict['logs'] = []
        
        return receipt_dict
    
    def _print_validation_result(self, result: Dict[str, Any]):
        """
        打印验证结果
        
        Args:
            result: 验证结果字典
        """
        print(f"\n验证结果:")
        print(f"  通过: {'✅ 是' if result.get('passed') else '❌ 否'}")
        print(f"  得分: {result.get('score', 0)} / {result.get('max_score', 0)}")
        
        if result.get('checks'):
            print(f"\n检查项:")
            for check in result['checks']:
                status = "✅" if check.get('passed') else "❌"
                print(f"    {status} {check.get('name')}: {check.get('message', '')}")
        
        if result.get('feedback'):
            print(f"\n反馈: {result.get('feedback')}")

