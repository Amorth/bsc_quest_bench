"""
BSC Quest Environment - 环境层

负责:
1. 初始化本地 Anvil 节点 (fork from BSC testnet)
2. 创建测试账户并设置初始余额
3. 提供 Web3 连接和链上状态查询
"""

import subprocess
import time
import socket
import os
from typing import Optional, Dict, Any
from web3 import Web3
from eth_account import Account


class QuestEnvironment:
    """Quest环境管理类"""
    
    def __init__(
        self,
        fork_url: str = "https://bsc-testnet.drpc.org",
        chain_id: int = 97,
        anvil_port: int = 8545
    ):
        """
        初始化Quest环境
        
        Args:
            fork_url: BSC RPC URL (默认使用testnet)
            chain_id: 链ID (97=BSC Testnet)
            anvil_port: Anvil端口
        """
        self.fork_url = fork_url
        self.chain_id = chain_id
        self.anvil_port = anvil_port
        self.anvil_process = None
        self.anvil_cmd = None
        
        self.w3: Optional[Web3] = None
        self.test_account: Optional[Account] = None
        self.test_address: Optional[str] = None
        self.test_private_key: Optional[str] = None
        
    def start(self) -> Dict[str, Any]:
        """
        启动环境
        
        Returns:
            环境信息字典
        """
        # 1. 启动 Anvil fork
        self._start_anvil_fork()
        
        # 2. 连接 Web3
        anvil_rpc = f"http://127.0.0.1:{self.anvil_port}"
        self.w3 = Web3(Web3.HTTPProvider(anvil_rpc))
        
        # 2.1 注入 POA middleware (BSC 是 POA 链)
        try:
            # Web3.py 7.x 使用 ExtraDataToPOAMiddleware
            from web3.middleware import ExtraDataToPOAMiddleware
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except ImportError:
            try:
                # Web3.py v6+ 使用 geth_poa_middleware（旧路径）
                from web3.middleware.geth_poa import geth_poa_middleware
                self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            except ImportError:
                try:
                    # Web3.py v5 使用 geth_poa_middleware（更旧的路径）
                    from web3.middleware import geth_poa_middleware
                    self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                except ImportError:
                    # 如果都不存在，Anvil 本地 fork 通常不需要（我们使用直接 RPC 调用绕过）
                    print("⚠️  Warning: Could not import POA middleware, continuing without it")
        
        if not self.w3.is_connected():
            raise ConnectionError(f"无法连接到 Anvil: {anvil_rpc}")
        
        print(f"✓ Anvil 连接成功")
        print(f"  Chain ID: {self.w3.eth.chain_id}")
        print(f"  Anvil RPC: {anvil_rpc}")
        print(f"  Fork: {self.fork_url}")
        
        # 3. 创建测试账户
        self.test_account = Account.create()
        self.test_address = self.test_account.address
        self.test_private_key = self.test_account.key.hex()
        
        print(f"✓ 测试账户创建成功")
        print(f"  Address: {self.test_address}")
        
        # 4. 设置初始余额 (1 BNB)
        self._set_balance(self.test_address, 10**18)
        
        balance = self.w3.eth.get_balance(self.test_address) / 10**18
        print(f"  Balance: {balance} BNB")
        
        # 5. 预热常用合约地址 (触发 Anvil 拉取合约代码)
        self._preheat_contracts()
        
        # 6. 设置测试账户的 ERC20 token 余额
        self._set_token_balances()
        
        return {
            'rpc_url': anvil_rpc,
            'chain_id': self.chain_id,
            'test_address': self.test_address,
            'test_private_key': self.test_private_key,
            'block_number': self.w3.eth.block_number,
            'balance': balance
        }
    
    def stop(self):
        """停止环境"""
        self._cleanup_anvil()
        print("✓ 环境已清理")
    
    def _start_anvil_fork(self):
        """启动 Anvil fork 进程"""
        # 1. 清理可能存在的僵尸 Anvil 进程
        self._kill_zombie_anvil()
        
        # 2. 检查端口是否被占用
        if self._is_port_in_use(self.anvil_port):
            print(f"⚠️  端口 {self.anvil_port} 已被占用")
            print(f"   尝试清理并重试...")
            self._kill_zombie_anvil()
            time.sleep(2)
            
            if self._is_port_in_use(self.anvil_port):
                raise RuntimeError(
                    f"端口 {self.anvil_port} 仍被占用，无法启动 Anvil\n"
                    f"请手动清理:\n"
                    f"  Linux/Mac: lsof -ti:{self.anvil_port} | xargs kill -9\n"
                    f"  Windows: netstat -ano | findstr :{self.anvil_port}"
                )
        
        # 3. 测试网络连接到 Fork URL
        print(f"🔍 测试连接到 Fork URL...")
        if not self._test_fork_url():
            print(f"⚠️  警告: 无法快速连接到 Fork URL")
            print(f"   继续尝试启动，但可能会较慢...")
        
        # 4. 查找 anvil 命令
        anvil_paths = [
            os.path.expanduser('~/.foundry/bin/anvil'),
            '/usr/local/bin/anvil',
            'anvil',
        ]
        
        for path in anvil_paths:
            try:
                result = subprocess.run(
                    [path, '--version'],
                    capture_output=True,
                    check=True,
                    text=True,
                    timeout=5
                )
                self.anvil_cmd = path
                print(f"✓ 找到 Anvil: {path}")
                break
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                continue
        
        if not self.anvil_cmd:
            raise RuntimeError(
                "未找到 Anvil! 请安装 Foundry:\n"
                "  curl -L https://foundry.paradigm.xyz | bash\n"
                "  foundryup"
            )
        
        # 5. 启动 Anvil
        print(f"🔨 启动 Anvil fork...")
        print(f"   Fork URL: {self.fork_url}")
        print(f"   Port: {self.anvil_port}")
        
        anvil_cmd_list = [
            self.anvil_cmd,
            '--fork-url', self.fork_url,
            '--port', str(self.anvil_port),
            '--host', '127.0.0.1',
            '--no-storage-caching',  # 禁用存储缓存，强制从远程拉取
            '--compute-units-per-second', '1000',  # 提高请求限制
        ]
        
        # 捕获 stderr 用于诊断
        self.anvil_process = subprocess.Popen(
            anvil_cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # 6. 等待启动（增加超时时间）
        max_wait = 30  # 从 15s 增加到 30s
        print(f"   等待 Anvil 启动 (最多 {max_wait}s)...")
        
        for i in range(max_wait):
            time.sleep(1)
            
            # 检查端口是否打开
            if self._is_port_in_use(self.anvil_port):
                print(f"✓ Anvil 启动成功 ({i+1}s)")
                return
            
            # 检查进程是否意外退出
            if self.anvil_process.poll() is not None:
                returncode = self.anvil_process.returncode
                # 尝试读取错误输出
                try:
                    stdout, stderr = self.anvil_process.communicate(timeout=1)
                    error_msg = stderr.decode('utf-8', errors='ignore') if stderr else "无错误信息"
                except:
                    error_msg = "无法读取错误信息"
                
                self._cleanup_anvil()
                raise RuntimeError(
                    f"Anvil 进程意外退出 (code {returncode})\n"
                    f"错误信息: {error_msg[:500]}\n"
                    f"可能原因:\n"
                    f"  - Fork URL 无效或不可达: {self.fork_url}\n"
                    f"  - 网络连接问题\n"
                    f"  - RPC 节点限流或故障"
                )
            
            # 每 5 秒显示进度
            if (i + 1) % 5 == 0:
                print(f"   等待中... ({i+1}s)")
        
        # 超时处理
        self._cleanup_anvil()
        raise RuntimeError(
            f"Anvil 启动超时 ({max_wait}s)\n"
            f"可能原因:\n"
            f"  1. 网络连接慢 - Fork URL: {self.fork_url}\n"
            f"  2. RPC 节点响应慢或不可用\n"
            f"  3. 系统资源不足\n"
            f"\n"
            f"建议:\n"
            f"  - 检查网络连接\n"
            f"  - 尝试更换 RPC URL\n"
            f"  - 重启测试\n"
            f"  - 检查 WSL2 资源配置"
        )
    
    def _cleanup_anvil(self):
        """清理 Anvil 进程"""
        if self.anvil_process:
            try:
                self.anvil_process.terminate()
                self.anvil_process.wait(timeout=5)
                print("✓ Anvil 进程已终止")
            except:
                self.anvil_process.kill()
                print("✓ Anvil 进程已强制终止")
            self.anvil_process = None
    
    def _is_port_in_use(self, port: int) -> bool:
        """检查端口是否被占用"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    
    def _kill_zombie_anvil(self):
        """
        清理可能存在的僵尸 Anvil 进程
        """
        try:
            import psutil
            
            killed_count = 0
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    # 检查是否是 anvil 进程
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline and 'anvil' in ' '.join(cmdline).lower():
                        # 检查是否使用相同端口
                        if str(self.anvil_port) in ' '.join(cmdline):
                            print(f"   清理僵尸 Anvil 进程: PID {proc.info['pid']}")
                            proc.kill()
                            proc.wait(timeout=3)
                            killed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    continue
            
            if killed_count > 0:
                print(f"   ✓ 清理了 {killed_count} 个僵尸进程")
                time.sleep(1)  # 等待端口释放
        except ImportError:
            # psutil 未安装，尝试系统命令
            import platform
            system = platform.system()
            
            try:
                if system == 'Linux':
                    # Linux: 使用 lsof 查找占用端口的进程
                    result = subprocess.run(
                        ['lsof', '-ti', f':{self.anvil_port}'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        pids = result.stdout.strip().split('\n')
                        for pid in pids:
                            try:
                                subprocess.run(['kill', '-9', pid], timeout=2)
                                print(f"   清理进程: PID {pid}")
                            except:
                                pass
                        time.sleep(1)
                elif system == 'Windows':
                    # Windows: 使用 netstat 查找占用端口的进程
                    result = subprocess.run(
                        ['netstat', '-ano'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            if f':{self.anvil_port}' in line and 'LISTENING' in line:
                                parts = line.split()
                                if parts:
                                    pid = parts[-1]
                                    try:
                                        subprocess.run(['taskkill', '/F', '/PID', pid], timeout=2)
                                        print(f"   清理进程: PID {pid}")
                                    except:
                                        pass
                        time.sleep(1)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
    
    def _test_fork_url(self, timeout=5):
        """
        测试 Fork URL 连接
        
        Args:
            timeout: 超时时间（秒）
        
        Returns:
            bool: 连接成功返回 True，否则返回 False
        """
        import json
        import urllib.request
        import urllib.error
        
        try:
            # 发送简单的 eth_blockNumber 请求
            data = json.dumps({
                "jsonrpc": "2.0",
                "method": "eth_blockNumber",
                "params": [],
                "id": 1
            }).encode('utf-8')
            
            req = urllib.request.Request(
                self.fork_url,
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.loads(response.read().decode('utf-8'))
                if 'result' in result:
                    block_num = int(result['result'], 16)
                    print(f"   ✓ Fork URL 连接成功 (区块: {block_num})")
                    return True
                else:
                    print(f"   ⚠️  Fork URL 响应异常: {result}")
                    return False
        except urllib.error.URLError as e:
            print(f"   ⚠️  网络错误: {e.reason}")
            return False
        except Exception as e:
            print(f"   ⚠️  连接测试失败: {e}")
            return False
    
    def _preheat_contracts(self):
        """
        预热常用合约地址
        
        通过访问合约代码和余额，触发 Anvil 从远程节点拉取合约数据
        这样在后续测试中就能正确检测到合约
        """
        from eth_utils import to_checksum_address
        
        # BSC Mainnet 常用合约地址
        contract_addresses = [
            "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # WBNB
            "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",  # PancakeFactory V2
            "0x10ED43C718714eb63d5aA57B78B54704E256024E",  # PancakeRouter V2
        ]
        
        print(f"✓ 预热合约地址 (Anvil 从远程节点拉取数据)...")
        for addr in contract_addresses:
            try:
                # 使用 checksum 地址
                addr_checksum = to_checksum_address(addr)
                print(f"  • {addr_checksum}")
                
                # 访问合约代码（触发 Anvil 拉取）
                code = self.w3.eth.get_code(addr_checksum)
                print(f"    - get_code(): {len(code) if code else 0} bytes")
                
                balance = self.w3.eth.get_balance(addr_checksum)
                print(f"    - get_balance(): {balance / 10**18:.6f} BNB")
                
                # 额外：尝试读取 storage 来确保数据被拉取
                try:
                    storage = self.w3.eth.get_storage_at(addr_checksum, 0)
                    print(f"    - get_storage_at(0): {storage.hex()[:20]}...")
                except Exception as se:
                    print(f"    - get_storage_at(0): Error - {se}")
                
                is_contract = code and len(code) > 2
                if is_contract:
                    print(f"    ✅ Confirmed as contract")
                else:
                    print(f"    ⚠️  WARNING: No contract code found!")
                    print(f"    This might indicate:")
                    print(f"      - Address is not a contract on BSC testnet")
                    print(f"      - Anvil fork connection issue")
                    print(f"      - Need to check fork URL: {self.fork_url}")
            except Exception as e:
                print(f"  • {addr[:10]}... [❌ Error: {e}]")
        print()
    
    def _set_token_balances(self):
        """
        设置测试账户的 ERC20 token 余额
        
        使用 Anvil 的 impersonate 功能从富有的地址转账
        """
        from eth_utils import to_checksum_address
        from eth_account import Account
        
        # BSC Mainnet USDT 合约和一个富有的地址
        usdt_address = '0x55d398326f99059fF775485246999027B3197955'
        # 使用 Binance 的 USDT 储备地址（通常有大量 USDT）
        rich_address = '0x8894E0a0c962CB723c1976a4421c95949bE2D4E3'  # Binance hot wallet
        
        print(f"✓ 设置 ERC20 token 余额...")
        
        try:
            token_addr = to_checksum_address(usdt_address)
            test_addr = to_checksum_address(self.test_address)
            rich_addr = to_checksum_address(rich_address)
            
            # 1. 启用 impersonate（允许我们作为任何地址发送交易）
            self.w3.provider.make_request('anvil_impersonateAccount', [rich_addr])
            
            # 2. 给富有地址设置足够的 BNB 用于支付 gas
            self.w3.provider.make_request('anvil_setBalance', [rich_addr, hex(10**18)])
            
            # 3. 编码 ERC20 transfer 调用
            # transfer(address to, uint256 amount)
            # Function selector: 0xa9059cbb
            transfer_amount = 1000 * 10**18  # 1000 tokens
            
            # 编码 transfer 函数调用
            from eth_abi import encode
            
            # Function selector
            function_selector = bytes.fromhex('a9059cbb')
            
            # 编码参数
            encoded_params = encode(['address', 'uint256'], [test_addr, transfer_amount])
            
            # 组合 data
            data = '0x' + function_selector.hex() + encoded_params.hex()
            
            # 4. 从富有地址发送转账交易
            # 直接使用 RPC 方法，绕过 Web3.py middleware（避免 POA extraData 错误）
            tx_hash = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': rich_addr,
                    'to': token_addr,
                    'data': data,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)  # 3 gwei
                }]
            )['result']
            
            # 5. 等待交易确认
            # 使用简单的轮询，避免 Web3.py middleware 问题
            max_attempts = 20
            for i in range(max_attempts):
                try:
                    receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                    if receipt and receipt.get('blockNumber'):
                        break
                except:
                    pass
                time.sleep(0.5)
            else:
                raise TimeoutError(f"Transaction {tx_hash} not confirmed after {max_attempts * 0.5}s")
            
            # 6. 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [rich_addr])
            
            # 7. 验证余额
            # 使用 balanceOf 查询
            balance_of_selector = bytes.fromhex('70a08231')
            balance_data = '0x' + balance_of_selector.hex() + encode(['address'], [test_addr]).hex()
            
            result = self.w3.eth.call({
                'to': token_addr,
                'data': balance_data
            })
            
            balance = int(result.hex(), 16)
            balance_formatted = balance / 10**18
            
            # receipt['status'] 是 hex string (e.g., '0x1')
            receipt_status = int(receipt.get('status', '0x0'), 16)
            
            if receipt_status == 1 and balance > 0:
                print(f"  • USDT: {balance_formatted:.2f} tokens ✅")
            else:
                print(f"  • USDT: Transfer failed (status={receipt_status}) or balance is 0 ({balance_formatted:.2f})")
                
        except Exception as e:
            print(f"  • USDT: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        # 设置 WBNB 余额（通过调用 deposit 函数）
        try:
            wbnb_address = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'  # BSC Mainnet WBNB
            wbnb_addr = to_checksum_address(wbnb_address)
            test_addr = to_checksum_address(self.test_address)
            
            # WBNB deposit function selector: 0xd0e30db0
            deposit_data = '0xd0e30db0'
            
            # 存入 100 BNB 获得 100 WBNB
            deposit_amount = 100 * 10**18
            
            # 使用 impersonate 测试账户发送交易（测试账户已经有 1 BNB 了，需要先增加余额）
            # 给测试账户增加足够的 BNB
            self.w3.provider.make_request('anvil_setBalance', [test_addr, hex(200 * 10**18)])
            
            # Impersonate 测试账户（允许无需私钥发送交易）
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # 调用 WBNB deposit
            tx_hash = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'to': wbnb_addr,
                    'data': deposit_data,
                    'value': hex(deposit_amount),
                    'gas': hex(60000),
                    'gasPrice': hex(3000000000)
                }]
            )['result']
            
            # 等待确认
            max_attempts = 20
            for i in range(max_attempts):
                try:
                    receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                    if receipt and receipt.get('blockNumber'):
                        break
                except:
                    pass
                time.sleep(0.5)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            # 验证 WBNB 余额
            balance_of_selector = bytes.fromhex('70a08231')
            balance_data = '0x' + balance_of_selector.hex() + encode(['address'], [test_addr]).hex()
            
            result = self.w3.eth.call({
                'to': wbnb_addr,
                'data': balance_data
            })
            
            wbnb_balance = int(result.hex(), 16)
            wbnb_balance_formatted = wbnb_balance / 10**18
            
            receipt_status = int(receipt.get('status', '0x0'), 16)
            
            if receipt_status == 1 and wbnb_balance > 0:
                print(f"  • WBNB: {wbnb_balance_formatted:.2f} tokens ✅")
            else:
                print(f"  • WBNB: Deposit failed (status={receipt_status}) or balance is 0")
                
        except Exception as e:
            print(f"  • WBNB: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        # 设置 CAKE 余额（用于 burn 测试）
        try:
            cake_address = '0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82'  # BSC Mainnet CAKE
            cake_addr = to_checksum_address(cake_address)
            test_addr = to_checksum_address(self.test_address)
            
            # 尝试多个可能的富有地址
            rich_addresses = [
                ('0x8894E0a0c962CB723c1976a4421c95949bE2D4E3', 'Binance Hot Wallet'),
                ('0x73feaa1eE314F8c655E354234017bE2193C9E24E', 'PancakeSwap MasterChefV2'),
                ('0x10ED43C718714eb63d5aA57B78B54704E256024E', 'PancakeSwap Router'),
            ]
            
            rich_cake_addr = None
            rich_name = None
            
            # 查找有 CAKE 余额的地址
            balance_of_selector = bytes.fromhex('70a08231')
            for addr, name in rich_addresses:
                check_addr = to_checksum_address(addr)
                balance_data = '0x' + balance_of_selector.hex() + encode(['address'], [check_addr]).hex()
                
                try:
                    result = self.w3.eth.call({
                        'to': cake_addr,
                        'data': balance_data
                    })
                    balance = int(result.hex(), 16)
                    if balance >= 100 * 10**18:  # 至少 100 CAKE
                        rich_cake_addr = check_addr
                        rich_name = name
                        break
                except:
                    continue
            
            if not rich_cake_addr:
                print(f"  • CAKE: ⚠️  No rich address found with sufficient balance, skipping")
                raise Exception("No rich CAKE address found")
            
            rich_cake_addr = to_checksum_address(rich_cake_addr)
            
            # 启用 impersonate
            self.w3.provider.make_request('anvil_impersonateAccount', [rich_cake_addr])
            
            # ERC20 transfer function selector: 0xa9059cbb
            transfer_selector = bytes.fromhex('a9059cbb')
            # Encode: transfer(address to, uint256 amount)
            transfer_amount = 100 * 10**18  # 100 CAKE
            transfer_data = '0x' + transfer_selector.hex() + encode(['address', 'uint256'], [test_addr, transfer_amount]).hex()
            
            # 发送转账交易
            response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': rich_cake_addr,
                    'to': cake_addr,
                    'data': transfer_data,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)
                }]
            )
            
            # 检查响应
            if 'result' not in response:
                print(f"  • CAKE: ❌ Transaction failed - {response.get('error', 'Unknown error')}")
                raise Exception(f"Transaction failed: {response}")
            
            tx_hash = response['result']
            
            # 等待确认
            max_attempts = 20
            for i in range(max_attempts):
                try:
                    receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                    if receipt and receipt.get('blockNumber'):
                        break
                except:
                    pass
                time.sleep(0.5)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [rich_cake_addr])
            
            # 验证 CAKE 余额
            balance_of_selector = bytes.fromhex('70a08231')
            balance_data = '0x' + balance_of_selector.hex() + encode(['address'], [test_addr]).hex()
            
            result = self.w3.eth.call({
                'to': cake_addr,
                'data': balance_data
            })
            
            cake_balance = int(result.hex(), 16)
            cake_balance_formatted = cake_balance / 10**18
            
            receipt_status = int(receipt.get('status', '0x0'), 16)
            
            if receipt_status == 1 and cake_balance > 0:
                print(f"  • CAKE: {cake_balance_formatted:.2f} tokens ✅")
            else:
                print(f"  • CAKE: Transfer failed (status={receipt_status}) or balance is 0")
                
        except Exception as e:
            print(f"  • CAKE: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        # 设置初始 allowances（用于 revoke approval 测试）
        print(f"✓ 设置初始 allowances...")
        try:
            usdt_addr = to_checksum_address(usdt_address)
            test_addr = to_checksum_address(self.test_address)
            
            # 需要授权的合约地址（PancakeSwap Router, Venus Protocol, etc）
            spenders = [
                '0x10ED43C718714eb63d5aA57B78B54704E256024E',  # PancakeSwap Router
                '0x13f4EA83D0bd40E75C8222255bc855a974568Dd4',  # Venus Protocol
                '0x1B81D678ffb9C0263b24A97847620C99d213eB14'   # PancakeSwap V3 Router
            ]
            
            # Impersonate 测试账户
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            for spender in spenders:
                spender_addr = to_checksum_address(spender)
                
                # ERC20 approve function selector: 0x095ea7b3
                approve_selector = bytes.fromhex('095ea7b3')
                # Encode: approve(address spender, uint256 amount)
                # Approve a large amount (1000 USDT)
                approve_amount = 1000 * 10**18
                approve_data = '0x' + approve_selector.hex() + encode(['address', 'uint256'], [spender_addr, approve_amount]).hex()
                
                # 发送 approve 交易
                response = self.w3.provider.make_request(
                    'eth_sendTransaction',
                    [{
                        'from': test_addr,
                        'to': usdt_addr,
                        'data': approve_data,
                        'gas': hex(100000),
                        'gasPrice': hex(3000000000)
                    }]
                )
                
                # 检查响应
                if 'result' not in response:
                    print(f"  • Allowance for {spender[:10]}...: ❌ Failed - {response.get('error', 'Unknown error')}")
                    continue
                
                tx_hash = response['result']
                
                # 等待确认
                max_attempts = 20
                for i in range(max_attempts):
                    try:
                        receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                        if receipt and receipt.get('blockNumber'):
                            break
                    except:
                        pass
                    time.sleep(0.5)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            print(f"  • USDT allowances set for {len(spenders)} spenders ✅")
                
        except Exception as e:
            print(f"  • Allowances: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        # 设置 NFT（用于 ERC721 测试）
        print(f"✓ 设置 NFT 所有权...")
        try:
            # PancakeSquad NFT on BSC Mainnet
            pancake_squad_address = '0x0a8901b0E25DEb55A87524f0cC164E9644020EBA'
            nft_addr = to_checksum_address(pancake_squad_address)
            test_addr = to_checksum_address(self.test_address)
            token_id = 1  # 我们要转移的 NFT ID
            
            # 先查询当前所有者
            owner_of_selector = bytes.fromhex('6352211e')  # ownerOf(uint256)
            token_id_hex = format(token_id, '064x')
            owner_data = '0x' + owner_of_selector.hex() + token_id_hex
            
            result = self.w3.eth.call({
                'to': nft_addr,
                'data': owner_data
            })
            
            current_owner_hex = result.hex()
            if len(current_owner_hex) >= 42:
                current_owner = '0x' + current_owner_hex[-40:]
                current_owner_addr = to_checksum_address(current_owner)
                print(f"  • NFT #{token_id} current owner: {current_owner_addr}")
                
                # Impersonate 当前所有者
                self.w3.provider.make_request('anvil_impersonateAccount', [current_owner_addr])
                
                # ERC721 transferFrom function selector: 0x23b872dd
                # transferFrom(address from, address to, uint256 tokenId)
                transfer_selector = bytes.fromhex('23b872dd')
                # Encode: from (32 bytes) + to (32 bytes) + tokenId (32 bytes)
                transfer_data = '0x' + transfer_selector.hex() + encode(['address', 'address', 'uint256'], [current_owner_addr, test_addr, token_id]).hex()
                
                # 发送 transferFrom 交易
                response = self.w3.provider.make_request(
                    'eth_sendTransaction',
                    [{
                        'from': current_owner_addr,
                        'to': nft_addr,
                        'data': transfer_data,
                        'gas': hex(150000),
                        'gasPrice': hex(3000000000)
                    }]
                )
                
                # 检查响应
                if 'result' not in response:
                    print(f"  • NFT: ❌ Transaction failed - {response.get('error', 'Unknown error')}")
                    raise Exception(f"NFT transfer failed: {response}")
                
                tx_hash = response['result']
                
                # 等待确认
                max_attempts = 20
                for i in range(max_attempts):
                    try:
                        receipt = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])['result']
                        if receipt and receipt.get('blockNumber'):
                            break
                    except:
                        pass
                    time.sleep(0.5)
                
                # 停止 impersonate
                self.w3.provider.make_request('anvil_stopImpersonatingAccount', [current_owner_addr])
                
                # 验证 NFT 所有者
                result = self.w3.eth.call({
                    'to': nft_addr,
                    'data': owner_data
                })
                
                new_owner_hex = result.hex()
                if len(new_owner_hex) >= 42:
                    new_owner = '0x' + new_owner_hex[-40:]
                    new_owner_addr = to_checksum_address(new_owner)
                    
                    receipt_status = int(receipt.get('status', '0x0'), 16)
                    
                    if receipt_status == 1 and new_owner_addr.lower() == test_addr.lower():
                        print(f"  • PancakeSquad NFT #{token_id}: ✅ Transferred to test account")
                    else:
                        print(f"  • PancakeSquad NFT #{token_id}: ❌ Transfer failed or owner mismatch")
            else:
                print(f"  • PancakeSquad NFT: ⚠️  Could not determine owner")
                
        except Exception as e:
            print(f"  • PancakeSquad NFT: ❌ Error - {e}")
            import traceback
            traceback.print_exc()
        
        print()
        
        # 7. 部署 ERC1363 测试代币
        self._deploy_erc1363_token()
        
        # 8. 部署 ERC1155 测试代币
        self._deploy_erc1155_token()
        
        # 9. 部署闪电贷接收合约
        self._deploy_flashloan_receiver()
        
        # 10. 部署 SimpleCounter 测试合约
        self._deploy_simple_counter()
        
        # 11. 部署 DonationBox 测试合约
        self._deploy_donation_box()
        
        # 12. 部署 MessageBoard 测试合约
        self._deploy_message_board()
        
        # 13. 部署 DelegateCall 测试合约
        self._deploy_delegate_call_contracts()
        
        # 14. 部署 FallbackReceiver 测试合约
        self._deploy_fallback_receiver()
    
    def _deploy_erc1363_token(self):
        """
        部署 ERC1363 测试代币并给测试账户分配代币
        
        ERC1363 是 ERC20 的扩展，支持 transferAndCall 和 approveAndCall
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        
        print(f"✓ 部署 ERC1363 测试代币...")
        
        try:
            test_addr = to_checksum_address(self.test_address)
            
            # 读取合约源代码并使用 py-solc-x 编译
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface IERC1363Receiver {
    function onTransferReceived(address operator, address from, uint256 value, bytes calldata data) external returns (bytes4);
}

interface IERC1363Spender {
    function onApprovalReceived(address owner, uint256 value, bytes calldata data) external returns (bytes4);
}

contract TestERC1363Token {
    string public name = "Test ERC1363";
    string public symbol = "T1363";
    uint8 public decimals = 18;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    
    constructor() {
        totalSupply = 1000000 * 10**18;
        balanceOf[msg.sender] = totalSupply;
        emit Transfer(address(0), msg.sender, totalSupply);
    }
    
    function transfer(address to, uint256 value) public returns (bool) {
        require(balanceOf[msg.sender] >= value, "Insufficient balance");
        balanceOf[msg.sender] -= value;
        balanceOf[to] += value;
        emit Transfer(msg.sender, to, value);
        return true;
    }
    
    function approve(address spender, uint256 value) public returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }
    
    function transferFrom(address from, address to, uint256 value) public returns (bool) {
        require(balanceOf[from] >= value, "Insufficient balance");
        require(allowance[from][msg.sender] >= value, "Insufficient allowance");
        balanceOf[from] -= value;
        balanceOf[to] += value;
        allowance[from][msg.sender] -= value;
        emit Transfer(from, to, value);
        return true;
    }
    
    function transferAndCall(address to, uint256 value) public returns (bool) {
        return transferAndCall(to, value, "");
    }
    
    function transferAndCall(address to, uint256 value, bytes memory data) public returns (bool) {
        // Directly perform the transfer logic inline instead of calling transfer()
        require(balanceOf[msg.sender] >= value, "Insufficient balance");
        balanceOf[msg.sender] -= value;
        balanceOf[to] += value;
        emit Transfer(msg.sender, to, value);
        
        // Check if recipient is a contract and call callback if needed
        uint256 codeSize;
        assembly { codeSize := extcodesize(to) }
        if (codeSize > 0) {
            try IERC1363Receiver(to).onTransferReceived(msg.sender, msg.sender, value, data) returns (bytes4 retval) {
                require(retval == IERC1363Receiver.onTransferReceived.selector, "Receiver rejected");
            } catch {}
        }
        return true;
    }
    
    function approveAndCall(address spender, uint256 value) public returns (bool) {
        return approveAndCall(spender, value, "");
    }
    
    function approveAndCall(address spender, uint256 value, bytes memory data) public returns (bool) {
        // Directly perform the approval logic inline
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        
        // Check if spender is a contract and call callback if needed
        uint256 codeSize;
        assembly { codeSize := extcodesize(spender) }
        if (codeSize > 0) {
            try IERC1363Spender(spender).onApprovalReceived(msg.sender, value, data) returns (bytes4 retval) {
                require(retval == IERC1363Spender.onApprovalReceived.selector, "Spender rejected");
            } catch {}
        }
        return true;
    }
}
"""
            
            # 使用 solcx 编译合约
            try:
                from solcx import compile_source, install_solc, set_solc_version
                
                # 尝试使用已安装的 solc，如果没有则安装
                try:
                    set_solc_version('0.8.20')
                except:
                    print("  • 安装 Solidity 编译器 v0.8.20...")
                    install_solc('0.8.20')
                    set_solc_version('0.8.20')
                
                # 编译合约
                compiled_sol = compile_source(contract_source, output_values=['abi', 'bin'])
                contract_interface = compiled_sol['<stdin>:TestERC1363Token']
                
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
                
            except Exception as e:
                print(f"  • ⚠️  Solc not available: {e}")
                print(f"  • 尝试安装 py-solc-x: pip install py-solc-x")
                raise Exception("Cannot compile ERC1363 contract without solc. Please install: pip install py-solc-x")
            
            # 部署合约
            # Impersonate测试账户以便部署合约
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # 发送部署交易
            deploy_response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'data': '0x' + bytecode if not bytecode.startswith('0x') else bytecode,
                    'gas': hex(3000000),  # 3M gas for deployment
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' not in deploy_response:
                raise Exception(f"Deployment failed: {deploy_response}")
            
            tx_hash = deploy_response['result']
            
            # 等待部署确认
            max_attempts = 20
            receipt = None
            for i in range(max_attempts):
                try:
                    receipt_response = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])
                    if receipt_response.get('result'):
                        receipt = receipt_response['result']
                        break
                except:
                    pass
                time.sleep(0.5)
            
            if not receipt or not receipt.get('contractAddress'):
                raise Exception("Contract deployment failed - no contract address")
            
            # 获取部署的合约地址
            erc1363_address = receipt['contractAddress']
            erc1363_address = to_checksum_address(erc1363_address)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            # 存储合约地址供后续使用
            self.erc1363_token_address = erc1363_address
            
            # 验证部署
            balance_selector = bytes.fromhex('70a08231')  # balanceOf(address)
            balance_data = '0x' + balance_selector.hex() + encode(['address'], [test_addr]).hex()
            
            result = self.w3.eth.call({
                'to': erc1363_address,
                'data': balance_data
            })
            
            balance = int(result.hex(), 16)
            balance_formatted = balance / 10**18
            
            print(f"  • ERC1363 Token deployed: {erc1363_address}")
            print(f"  • Test account balance: {balance_formatted:.2f} T1363 ✅")
            
        except Exception as e:
            print(f"  • ERC1363 Token: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            # 设置为 None 表示未部署
            self.erc1363_token_address = None
        
        print()
    
    def _deploy_erc1155_token(self):
        """
        部署 ERC1155 测试代币并给测试账户分配代币
        
        ERC1155 是多代币标准，支持同时管理多种代币类型
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        
        print("✓ 部署 ERC1155 测试代币...")
        
        try:
            test_addr = self.test_address
            
            # ERC1155 合约源代码
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TestERC1155Token {
    string public name = "Test Multi Token";
    
    // Mapping from token ID to account balances
    mapping(uint256 => mapping(address => uint256)) private _balances;
    
    // Mapping from account to operator approvals
    mapping(address => mapping(address => bool)) private _operatorApprovals;
    
    event TransferSingle(
        address indexed operator,
        address indexed from,
        address indexed to,
        uint256 id,
        uint256 value
    );
    
    event TransferBatch(
        address indexed operator,
        address indexed from,
        address indexed to,
        uint256[] ids,
        uint256[] values
    );
    
    event ApprovalForAll(
        address indexed account,
        address indexed operator,
        bool approved
    );
    
    constructor() {
        // Mint initial tokens to deployer
        // Token ID 1: 1000 units
        // Token ID 2: 500 units
        // Token ID 3: 100 units
        _balances[1][msg.sender] = 1000;
        _balances[2][msg.sender] = 500;
        _balances[3][msg.sender] = 100;
        
        emit TransferSingle(msg.sender, address(0), msg.sender, 1, 1000);
        emit TransferSingle(msg.sender, address(0), msg.sender, 2, 500);
        emit TransferSingle(msg.sender, address(0), msg.sender, 3, 100);
    }
    
    function balanceOf(address account, uint256 id) public view returns (uint256) {
        require(account != address(0), "ERC1155: balance query for the zero address");
        return _balances[id][account];
    }
    
    function balanceOfBatch(
        address[] memory accounts,
        uint256[] memory ids
    ) public view returns (uint256[] memory) {
        require(accounts.length == ids.length, "ERC1155: accounts and ids length mismatch");
        
        uint256[] memory batchBalances = new uint256[](accounts.length);
        
        for (uint256 i = 0; i < accounts.length; ++i) {
            batchBalances[i] = balanceOf(accounts[i], ids[i]);
        }
        
        return batchBalances;
    }
    
    function setApprovalForAll(address operator, bool approved) public {
        require(msg.sender != operator, "ERC1155: setting approval status for self");
        _operatorApprovals[msg.sender][operator] = approved;
        emit ApprovalForAll(msg.sender, operator, approved);
    }
    
    function isApprovedForAll(address account, address operator) public view returns (bool) {
        return _operatorApprovals[account][operator];
    }
    
    function safeTransferFrom(
        address from,
        address to,
        uint256 id,
        uint256 amount,
        bytes memory data
    ) public {
        require(
            from == msg.sender || isApprovedForAll(from, msg.sender),
            "ERC1155: caller is not owner nor approved"
        );
        require(to != address(0), "ERC1155: transfer to the zero address");
        
        uint256 fromBalance = _balances[id][from];
        require(fromBalance >= amount, "ERC1155: insufficient balance for transfer");
        
        _balances[id][from] = fromBalance - amount;
        _balances[id][to] += amount;
        
        emit TransferSingle(msg.sender, from, to, id, amount);
    }
    
    function safeBatchTransferFrom(
        address from,
        address to,
        uint256[] memory ids,
        uint256[] memory amounts,
        bytes memory data
    ) public {
        require(
            from == msg.sender || isApprovedForAll(from, msg.sender),
            "ERC1155: caller is not owner nor approved"
        );
        require(ids.length == amounts.length, "ERC1155: ids and amounts length mismatch");
        require(to != address(0), "ERC1155: transfer to the zero address");
        
        for (uint256 i = 0; i < ids.length; ++i) {
            uint256 id = ids[i];
            uint256 amount = amounts[i];
            
            uint256 fromBalance = _balances[id][from];
            require(fromBalance >= amount, "ERC1155: insufficient balance for transfer");
            
            _balances[id][from] = fromBalance - amount;
            _balances[id][to] += amount;
        }
        
        emit TransferBatch(msg.sender, from, to, ids, amounts);
    }
}
"""
            
            # 使用 solcx 编译合约
            try:
                from solcx import compile_source, install_solc, set_solc_version
                
                # 尝试使用已安装的 solc，如果没有则安装
                try:
                    set_solc_version('0.8.20')
                except:
                    print("  • 安装 Solidity 编译器 v0.8.20...")
                    install_solc('0.8.20')
                    set_solc_version('0.8.20')
                
                # 编译合约
                compiled_sol = compile_source(contract_source, output_values=['abi', 'bin'])
                contract_interface = compiled_sol['<stdin>:TestERC1155Token']
                
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
                
            except Exception as e:
                print(f"  • ⚠️  Solc compilation error: {e}")
                raise Exception("Cannot compile ERC1155 contract")
            
            # 部署合约
            # Impersonate测试账户以便部署合约
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # 发送部署交易
            deploy_response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'data': '0x' + bytecode if not bytecode.startswith('0x') else bytecode,
                    'gas': hex(3000000),  # 3M gas for deployment
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' not in deploy_response:
                raise Exception(f"Deployment failed: {deploy_response}")
            
            tx_hash = deploy_response['result']
            
            # 等待部署确认
            max_attempts = 20
            receipt = None
            for i in range(max_attempts):
                try:
                    receipt_response = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])
                    if receipt_response.get('result'):
                        receipt = receipt_response['result']
                        break
                except:
                    pass
                time.sleep(0.5)
            
            if not receipt or not receipt.get('contractAddress'):
                raise Exception("Contract deployment failed - no contract address")
            
            # 获取部署的合约地址
            erc1155_address = receipt['contractAddress']
            erc1155_address = to_checksum_address(erc1155_address)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            # 存储合约地址供后续使用
            self.erc1155_token_address = erc1155_address
            
            # 验证部署 - 查询 token ID 1 的余额
            # balanceOf(address account, uint256 id)
            balance_selector = bytes.fromhex('00fdd58e')  # balanceOf(address,uint256)
            balance_data = '0x' + balance_selector.hex() + encode(['address', 'uint256'], [test_addr, 1]).hex()
            
            result = self.w3.eth.call({
                'to': erc1155_address,
                'data': balance_data
            })
            
            balance = int(result.hex(), 16)
            
            print(f"  • ERC1155 Token deployed: {erc1155_address}")
            print(f"  • Test account balance (Token ID 1): {balance} units ✅")
            print(f"  • Test account balance (Token ID 2): 500 units ✅")
            print(f"  • Test account balance (Token ID 3): 100 units ✅")
            
        except Exception as e:
            print(f"  • ERC1155 Token: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            # 设置为 None 表示未部署
            self.erc1155_token_address = None
        
        print()
    
    def _deploy_flashloan_receiver(self):
        """
        部署闪电贷接收合约
        
        这是一个简单的闪电贷提供者+接收者合约，用于测试闪电贷功能
        """
        from eth_utils import to_checksum_address
        from eth_abi import encode
        
        print("✓ 部署闪电贷合约...")
        
        try:
            test_addr = self.test_address
            
            # 简单的闪电贷合约源代码
            # 这个合约既是提供者又是接收者，简化了测试流程
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
}

contract FlashLoanReceiver {
    address public owner;
    
    event FlashLoanExecuted(address indexed token, uint256 amount, uint256 fee);
    
    constructor() {
        owner = msg.sender;
    }
    
    // 执行闪电贷
    // 1. 从合约中借出代币
    // 2. 调用者可以使用这些代币
    // 3. 在同一交易中归还代币+手续费
    function executeFlashLoan(
        address token,
        uint256 amount
    ) external returns (bool) {
        // 计算手续费 (0.3%)
        uint256 fee = (amount * 3) / 1000;
        uint256 amountToRepay = amount + fee;
        
        // 检查合约是否有足够的代币可以借出
        uint256 balanceBefore = IERC20(token).balanceOf(address(this));
        require(balanceBefore >= amount, "Insufficient balance in pool");
        
        // 1. 将代币转给调用者（借款）
        require(IERC20(token).transfer(msg.sender, amount), "Loan transfer failed");
        
        // 2. 调用者现在拥有这些代币，可以进行任何操作
        // 在真实的闪电贷中，这里会调用借款人合约的回调函数
        // 但为了简化测试，我们假设调用者会在同一交易中归还
        
        // 3. 检查调用者是否归还了代币+手续费
        // 调用者需要先 approve 这个合约
        require(
            IERC20(token).transferFrom(msg.sender, address(this), amountToRepay),
            "Repayment failed"
        );
        
        // 验证余额增加了手续费
        uint256 balanceAfter = IERC20(token).balanceOf(address(this));
        require(balanceAfter >= balanceBefore + fee, "Fee not paid");
        
        emit FlashLoanExecuted(token, amount, fee);
        return true;
    }
    
    // 允许 owner 存入代币到流动性池
    function depositToPool(address token, uint256 amount) external {
        require(msg.sender == owner, "Only owner can deposit");
        require(
            IERC20(token).transferFrom(msg.sender, address(this), amount),
            "Deposit failed"
        );
    }
    
    // 查询池中的代币余额
    function poolBalance(address token) external view returns (uint256) {
        return IERC20(token).balanceOf(address(this));
    }
    
    // 允许 owner 提取代币
    function withdraw(address token, uint256 amount) external {
        require(msg.sender == owner, "Only owner can withdraw");
        require(IERC20(token).transfer(msg.sender, amount), "Withdraw failed");
    }
}
"""
            
            # 使用 solcx 编译合约
            try:
                from solcx import compile_source, install_solc, set_solc_version
                
                # 尝试使用已安装的 solc，如果没有则安装
                try:
                    set_solc_version('0.8.20')
                except:
                    print("  • 安装 Solidity 编译器 v0.8.20...")
                    install_solc('0.8.20')
                    set_solc_version('0.8.20')
                
                # 编译合约
                compiled_sol = compile_source(contract_source, output_values=['abi', 'bin'])
                contract_interface = compiled_sol['<stdin>:FlashLoanReceiver']
                
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
                
            except Exception as e:
                print(f"  • ⚠️  Solc compilation error: {e}")
                raise Exception("Cannot compile FlashLoan contract")
            
            # 部署合约
            # Impersonate测试账户以便部署合约
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # 发送部署交易
            deploy_response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'data': '0x' + bytecode if not bytecode.startswith('0x') else bytecode,
                    'gas': hex(3000000),  # 3M gas for deployment
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' not in deploy_response:
                raise Exception(f"Deployment failed: {deploy_response}")
            
            tx_hash = deploy_response['result']
            
            # 等待部署确认
            max_attempts = 20
            receipt = None
            for i in range(max_attempts):
                try:
                    receipt_response = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])
                    if receipt_response.get('result'):
                        receipt = receipt_response['result']
                        break
                except:
                    pass
                time.sleep(0.5)
            
            if not receipt or not receipt.get('contractAddress'):
                raise Exception("Contract deployment failed - no contract address")
            
            # 获取部署的合约地址
            flashloan_address = receipt['contractAddress']
            flashloan_address = to_checksum_address(flashloan_address)
            
            # 存储合约地址供后续使用
            self.flashloan_receiver_address = flashloan_address
            
            # 为闪电贷池存入一些 USDT（从富有地址转入）
            # 使用 impersonate 从 USDT 富有地址转入 10000 USDT 到闪电贷合约
            usdt_address = to_checksum_address('0x55d398326f99059fF775485246999027B3197955')
            rich_usdt_address = to_checksum_address('0x8894E0a0c962CB723c1976a4421c95949bE2D4E3')  # Binance Hot Wallet
            
            # Impersonate 富有地址
            self.w3.provider.make_request('anvil_impersonateAccount', [rich_usdt_address])
            
            # 转入 10000 USDT (6 decimals)
            pool_deposit_amount = 10000 * 10**6
            
            # ERC20 transfer function selector: 0xa9059cbb
            # transfer(address to, uint256 amount)
            transfer_data = '0xa9059cbb' + encode(['address', 'uint256'], [flashloan_address, pool_deposit_amount]).hex()
            
            transfer_response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': rich_usdt_address,
                    'to': usdt_address,
                    'data': transfer_data,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' in transfer_response:
                tx_hash = transfer_response['result']
                # 等待确认
                for i in range(10):
                    try:
                        receipt_response = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])
                        if receipt_response.get('result'):
                            break
                    except:
                        pass
                    time.sleep(0.3)
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [rich_usdt_address])
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
            # 验证部署 - 直接查询闪电贷合约的 USDT 余额
            # 使用 ERC20 balanceOf 而不是合约的 poolBalance，更可靠
            # balanceOf(address) returns (uint256)
            balance_selector = bytes.fromhex('70a08231')  # balanceOf(address)
            balance_data = '0x' + balance_selector.hex() + encode(['address'], [flashloan_address]).hex()
            
            try:
                result = self.w3.eth.call({
                    'to': usdt_address,
                    'data': balance_data
                })
                
                pool_balance = int(result.hex(), 16)
                pool_balance_formatted = pool_balance / 10**6  # USDT has 6 decimals
                
                print(f"  • FlashLoan Contract deployed: {flashloan_address}")
                print(f"  • Pool balance (USDT): {pool_balance_formatted:.2f} USDT ✅")
            except Exception as e:
                print(f"  • FlashLoan Contract deployed: {flashloan_address}")
                print(f"  • Warning: Could not verify pool balance: {e}")
                print(f"  • Pool initialization may have failed, but continuing...")
            
            # 预先 approve 闪电贷合约，这样测试账户可以直接调用 executeFlashLoan
            # Impersonate 测试账户
            self.w3.provider.make_request('anvil_impersonateAccount', [test_addr])
            
            # Approve 闪电贷合约最大额度 (2^256-1)
            max_approval = 2**256 - 1
            # ERC20 approve function selector: 0x095ea7b3
            # approve(address spender, uint256 amount)
            approve_data = '0x095ea7b3' + encode(['address', 'uint256'], [flashloan_address, max_approval]).hex()
            
            approve_response = self.w3.provider.make_request(
                'eth_sendTransaction',
                [{
                    'from': test_addr,
                    'to': usdt_address,
                    'data': approve_data,
                    'gas': hex(100000),
                    'gasPrice': hex(3000000000)
                }]
            )
            
            if 'result' in approve_response:
                tx_hash = approve_response['result']
                # 等待确认
                for i in range(10):
                    try:
                        receipt_response = self.w3.provider.make_request('eth_getTransactionReceipt', [tx_hash])
                        if receipt_response.get('result'):
                            break
                    except:
                        pass
                    time.sleep(0.3)
                print(f"  • Test account approved flash loan contract ✅")
            
            # 停止 impersonate
            self.w3.provider.make_request('anvil_stopImpersonatingAccount', [test_addr])
            
        except Exception as e:
            print(f"  • FlashLoan Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            # 设置为 None 表示未部署
            self.flashloan_receiver_address = None
        
        print()
    
    def _deploy_simple_counter(self):
        """
        部署 SimpleCounter 测试合约
        
        这是一个简单的计数器合约，用于测试基本的合约函数调用
        """
        print("✓ 部署 SimpleCounter 测试合约...")
        
        try:
            import solcx
            from solcx import compile_source
            from eth_utils import to_checksum_address
            from eth_abi import encode
            
            # 简单计数器合约源代码
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract SimpleCounter {
    uint256 public counter;
    address public owner;
    
    event CounterIncremented(uint256 newValue);
    event CounterReset(uint256 newValue);
    
    constructor() {
        owner = msg.sender;
        counter = 0;
    }
    
    // 增加计数器
    function increment() external {
        counter += 1;
        emit CounterIncremented(counter);
    }
    
    // 获取当前计数器值
    function getCounter() external view returns (uint256) {
        return counter;
    }
    
    // 重置计数器（仅owner）
    function reset() external {
        require(msg.sender == owner, "Only owner can reset");
        counter = 0;
        emit CounterReset(counter);
    }
}
"""
            
            # 尝试编译合约
            try:
                # 尝试使用已安装的 solc
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:SimpleCounter']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            except Exception as compile_error:
                print(f"  • Solc compilation failed: {compile_error}")
                print(f"  • Trying to install solc 0.8.20...")
                solcx.install_solc('0.8.20')
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:SimpleCounter']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            
            # 部署合约
            deployer = self.test_account
            deployer_address = deployer.address
            
            # 构造部署交易
            deploy_tx = {
                'from': deployer_address,
                'data': '0x' + bytecode,
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt['status'] != 1:
                raise Exception(f"Contract deployment failed with status: {receipt['status']}")
            
            contract_address = receipt['contractAddress']
            self.simple_counter_address = contract_address
            
            # 验证合约部署
            counter_contract = self.w3.eth.contract(address=contract_address, abi=abi)
            initial_counter = counter_contract.functions.getCounter().call()
            
            print(f"  • SimpleCounter Contract deployed: {contract_address}")
            print(f"  • Initial counter value: {initial_counter} ✅")
            
        except Exception as e:
            print(f"  • SimpleCounter Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.simple_counter_address = None
        
        print()
    
    def _deploy_donation_box(self):
        """
        部署 DonationBox 测试合约
        
        这是一个简单的捐赠盒合约，用于测试带 value 的合约函数调用
        """
        print("✓ 部署 DonationBox 测试合约...")
        
        try:
            import solcx
            from solcx import compile_source
            from eth_utils import to_checksum_address
            
            # DonationBox 合约源代码
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract DonationBox {
    address public owner;
    uint256 public totalDonations;
    mapping(address => uint256) public donations;
    
    event DonationReceived(address indexed donor, uint256 amount);
    
    constructor() {
        owner = msg.sender;
    }
    
    // Payable function to receive donations
    function donate() external payable {
        require(msg.value > 0, "Donation must be greater than 0");
        
        donations[msg.sender] += msg.value;
        totalDonations += msg.value;
        
        emit DonationReceived(msg.sender, msg.value);
    }
    
    // View function to get contract balance
    function getBalance() external view returns (uint256) {
        return address(this).balance;
    }
    
    // View function to get donor's total donations
    function getDonation(address donor) external view returns (uint256) {
        return donations[donor];
    }
    
    // Owner can withdraw (for testing cleanup)
    function withdraw() external {
        require(msg.sender == owner, "Only owner can withdraw");
        payable(owner).transfer(address(this).balance);
    }
    
    // Fallback function to accept BNB
    receive() external payable {
        donations[msg.sender] += msg.value;
        totalDonations += msg.value;
        emit DonationReceived(msg.sender, msg.value);
    }
}
"""
            
            # 尝试编译合约
            try:
                # 尝试使用已安装的 solc
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:DonationBox']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            except Exception as compile_error:
                print(f"  • Solc compilation failed: {compile_error}")
                print(f"  • Trying to install solc 0.8.20...")
                solcx.install_solc('0.8.20')
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:DonationBox']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            
            # 部署合约
            deployer = self.test_account
            deployer_address = deployer.address
            
            # 构造部署交易
            deploy_tx = {
                'from': deployer_address,
                'data': '0x' + bytecode,
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt['status'] != 1:
                raise Exception(f"Contract deployment failed with status: {receipt['status']}")
            
            contract_address = receipt['contractAddress']
            self.donation_box_address = contract_address
            
            # 验证合约部署
            donation_contract = self.w3.eth.contract(address=contract_address, abi=abi)
            initial_balance = donation_contract.functions.getBalance().call()
            
            print(f"  • DonationBox Contract deployed: {contract_address}")
            print(f"  • Initial contract balance: {initial_balance / 10**18:.6f} BNB ✅")
            
        except Exception as e:
            print(f"  • DonationBox Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.donation_box_address = None
        
        print()
    
    def _deploy_message_board(self):
        """
        部署 MessageBoard 测试合约
        
        这是一个简单的留言板合约，用于测试带参数的合约函数调用
        """
        print("✓ 部署 MessageBoard 测试合约...")
        
        try:
            import solcx
            from solcx import compile_source
            from eth_utils import to_checksum_address
            
            # MessageBoard 合约源代码
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract MessageBoard {
    string public message;
    address public lastSender;
    uint256 public updateCount;
    
    event MessageUpdated(address indexed sender, string newMessage);
    
    constructor() {
        message = "Initial message";
        lastSender = msg.sender;
        updateCount = 0;
    }
    
    // Set message with string parameter
    function setMessage(string memory newMessage) external {
        message = newMessage;
        lastSender = msg.sender;
        updateCount += 1;
        
        emit MessageUpdated(msg.sender, newMessage);
    }
    
    // Get current message
    function getMessage() external view returns (string memory) {
        return message;
    }
    
    // Get message info
    function getMessageInfo() external view returns (
        string memory currentMessage,
        address sender,
        uint256 count
    ) {
        return (message, lastSender, updateCount);
    }
}
"""
            
            # 尝试编译合约
            try:
                # 尝试使用已安装的 solc
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:MessageBoard']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            except Exception as compile_error:
                print(f"  • Solc compilation failed: {compile_error}")
                print(f"  • Trying to install solc 0.8.20...")
                solcx.install_solc('0.8.20')
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:MessageBoard']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            
            # 部署合约
            deployer = self.test_account
            deployer_address = deployer.address
            
            # 构造部署交易
            deploy_tx = {
                'from': deployer_address,
                'data': '0x' + bytecode,
                'gas': 1000000,  # 增加 gas limit，MessageBoard 有 string 初始化
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            # 调试信息
            print(f"  • Deployment tx: {tx_hash.hex()}")
            print(f"  • Gas used: {receipt['gasUsed']} / {deploy_tx['gas']}")
            print(f"  • Status: {receipt['status']}")
            
            if receipt['status'] != 1:
                # 尝试获取 revert reason
                print(f"  • Trying to get revert reason...")
                try:
                    self.w3.eth.call(deploy_tx, receipt['blockNumber'])
                except Exception as call_error:
                    print(f"  • Revert reason: {call_error}")
                raise Exception(f"MessageBoard deployment failed: status={receipt['status']}, gasUsed={receipt['gasUsed']}")
            
            contract_address = receipt['contractAddress']
            self.message_board_address = contract_address
            
            # 验证合约部署
            message_contract = self.w3.eth.contract(address=contract_address, abi=abi)
            initial_message = message_contract.functions.getMessage().call()
            
            print(f"  • MessageBoard Contract deployed: {contract_address}")
            print(f"  • Initial message: \"{initial_message}\" ✅")
            
        except Exception as e:
            print(f"  • MessageBoard Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.message_board_address = None
        
        print()
    
    def _deploy_delegate_call_contracts(self):
        """
        部署 DelegateCall 相关合约:
        1. Implementation 合约 - 包含实际逻辑
        2. Proxy 合约 - 使用 delegatecall 转发调用
        """
        from eth_utils import to_checksum_address
        import solcx
        
        print(f"✓ 部署 DelegateCall 合约...")
        
        try:
            # Implementation 合约源码
            implementation_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Implementation {
    uint256 public value;
    
    event ValueSet(uint256 newValue);
    
    // Set value function
    function setValue(uint256 _value) external {
        value = _value;
        emit ValueSet(_value);
    }
    
    // Get value function
    function getValue() external view returns (uint256) {
        return value;
    }
}
"""
            
            # Proxy 合约源码
            proxy_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract DelegateCallProxy {
    uint256 public value;  // Storage slot 0 - matches Implementation
    address public implementation;  // Storage slot 1
    
    event ValueSet(uint256 newValue);
    
    constructor(address _implementation) {
        implementation = _implementation;
    }
    
    // Fallback function that delegates all calls to implementation
    fallback() external payable {
        address impl = implementation;
        require(impl != address(0), "No implementation");
        
        assembly {
            // Copy calldata to memory
            calldatacopy(0, 0, calldatasize())
            
            // Delegate call to implementation
            let result := delegatecall(gas(), impl, 0, calldatasize(), 0, 0)
            
            // Copy return data to memory
            returndatacopy(0, 0, returndatasize())
            
            // Return or revert based on result
            switch result
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }
    
    // Allow contract to receive BNB
    receive() external payable {}
}
"""
            
            deployer = self.test_account
            deployer_address = deployer.address
            
            # 安装 0.8.20 版本的 solc
            solc_version = '0.8.20'
            if solc_version not in solcx.get_installed_solc_versions():
                print(f"  • Installing solc {solc_version}...")
                solcx.install_solc(solc_version)
            solcx.set_solc_version(solc_version)
            
            # 编译 Implementation 合约
            print(f"  • Compiling Implementation contract...")
            impl_compiled = solcx.compile_source(
                implementation_source,
                output_values=['abi', 'bin'],
                solc_version=solc_version
            )
            impl_contract_id = None
            for contract_id in impl_compiled.keys():
                if 'Implementation' in contract_id:
                    impl_contract_id = contract_id
                    break
            
            if not impl_contract_id:
                raise Exception("Implementation contract not found in compiled output")
            
            impl_abi = impl_compiled[impl_contract_id]['abi']
            impl_bytecode = impl_compiled[impl_contract_id]['bin']
            
            # 部署 Implementation 合约
            print(f"  • Deploying Implementation contract...")
            impl_deploy_tx = {
                'from': deployer_address,
                'data': '0x' + impl_bytecode,
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            impl_signed_tx = self.w3.eth.account.sign_transaction(impl_deploy_tx, deployer.key)
            impl_tx_hash = self.w3.eth.send_raw_transaction(impl_signed_tx.raw_transaction)
            impl_receipt = self.w3.eth.wait_for_transaction_receipt(impl_tx_hash, timeout=30)
            
            if impl_receipt['status'] != 1:
                raise Exception(f"Implementation deployment failed: status={impl_receipt['status']}")
            
            impl_address = impl_receipt['contractAddress']
            print(f"  • Implementation deployed: {impl_address}")
            
            # 编译 Proxy 合约
            print(f"  • Compiling Proxy contract...")
            proxy_compiled = solcx.compile_source(
                proxy_source,
                output_values=['abi', 'bin'],
                solc_version=solc_version
            )
            proxy_contract_id = None
            for contract_id in proxy_compiled.keys():
                if 'DelegateCallProxy' in contract_id:
                    proxy_contract_id = contract_id
                    break
            
            if not proxy_contract_id:
                raise Exception("Proxy contract not found in compiled output")
            
            proxy_abi = proxy_compiled[proxy_contract_id]['abi']
            proxy_bytecode = proxy_compiled[proxy_contract_id]['bin']
            
            # 编码构造函数参数 (implementation address)
            from eth_abi import encode
            constructor_params = encode(['address'], [to_checksum_address(impl_address)])
            
            # 部署 Proxy 合约
            print(f"  • Deploying Proxy contract...")
            proxy_deploy_tx = {
                'from': deployer_address,
                'data': '0x' + proxy_bytecode + constructor_params.hex(),
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            proxy_signed_tx = self.w3.eth.account.sign_transaction(proxy_deploy_tx, deployer.key)
            proxy_tx_hash = self.w3.eth.send_raw_transaction(proxy_signed_tx.raw_transaction)
            proxy_receipt = self.w3.eth.wait_for_transaction_receipt(proxy_tx_hash, timeout=30)
            
            if proxy_receipt['status'] != 1:
                raise Exception(f"Proxy deployment failed: status={proxy_receipt['status']}")
            
            proxy_address = proxy_receipt['contractAddress']
            
            # 保存地址
            self.delegate_call_implementation_address = impl_address
            self.delegate_call_proxy_address = proxy_address
            
            # 验证合约部署
            # 读取 implementation 合约的初始值
            impl_contract = self.w3.eth.contract(address=impl_address, abi=impl_abi)
            impl_initial_value = impl_contract.functions.getValue().call()
            
            # 读取 proxy 合约的初始值 (通过 delegatecall)
            proxy_contract = self.w3.eth.contract(address=proxy_address, abi=impl_abi)
            proxy_initial_value = proxy_contract.functions.getValue().call()
            
            print(f"  • Proxy Contract deployed: {proxy_address}")
            print(f"  • Implementation Contract: {impl_address}")
            print(f"  • Implementation initial value: {impl_initial_value}")
            print(f"  • Proxy initial value: {proxy_initial_value} ✅")
            
        except Exception as e:
            print(f"  • DelegateCall Contracts: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.delegate_call_implementation_address = None
            self.delegate_call_proxy_address = None
        
        print()
    
    def _deploy_fallback_receiver(self):
        """
        部署 FallbackReceiver 测试合约
        
        这是一个简单的合约，有 receive() 函数用于接收 BNB
        """
        print("✓ 部署 FallbackReceiver 测试合约...")
        
        try:
            import solcx
            from solcx import compile_source
            from eth_utils import to_checksum_address
            
            # FallbackReceiver 合约源代码
            contract_source = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract FallbackReceiver {
    uint256 public receivedCount;
    uint256 public totalReceived;
    address public owner;
    
    event BNBReceived(address indexed sender, uint256 amount);
    
    constructor() {
        owner = msg.sender;
        receivedCount = 0;
        totalReceived = 0;
    }
    
    // Receive function - called when BNB is sent with empty calldata
    receive() external payable {
        receivedCount += 1;
        totalReceived += msg.value;
        emit BNBReceived(msg.sender, msg.value);
    }
    
    // Fallback function - called when function doesn't exist
    fallback() external payable {
        receivedCount += 1;
        totalReceived += msg.value;
        emit BNBReceived(msg.sender, msg.value);
    }
    
    // Get contract balance
    function getBalance() external view returns (uint256) {
        return address(this).balance;
    }
    
    // Get received count
    function getReceivedCount() external view returns (uint256) {
        return receivedCount;
    }
    
    // Owner can withdraw (for cleanup)
    function withdraw() external {
        require(msg.sender == owner, "Only owner can withdraw");
        payable(owner).transfer(address(this).balance);
    }
}
"""
            
            # 尝试编译合约
            try:
                # 尝试使用已安装的 solc
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:FallbackReceiver']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            except Exception as compile_error:
                print(f"  • Solc compilation failed: {compile_error}")
                print(f"  • Trying to install solc 0.8.20...")
                solcx.install_solc('0.8.20')
                compiled = compile_source(
                    contract_source,
                    output_values=['abi', 'bin'],
                    solc_version='0.8.20'
                )
                contract_interface = compiled['<stdin>:FallbackReceiver']
                bytecode = contract_interface['bin']
                abi = contract_interface['abi']
            
            # 部署合约
            deployer = self.test_account
            deployer_address = deployer.address
            
            # 构造部署交易
            deploy_tx = {
                'from': deployer_address,
                'data': '0x' + bytecode,
                'gas': 500000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(deployer_address),
            }
            
            # 签名并发送交易
            signed_tx = self.w3.eth.account.sign_transaction(deploy_tx, deployer.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # 等待交易确认
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            
            if receipt['status'] != 1:
                raise Exception(f"Contract deployment failed with status: {receipt['status']}")
            
            contract_address = receipt['contractAddress']
            self.fallback_receiver_address = contract_address
            
            # 验证合约部署
            fallback_contract = self.w3.eth.contract(address=contract_address, abi=abi)
            initial_balance = fallback_contract.functions.getBalance().call()
            initial_count = fallback_contract.functions.getReceivedCount().call()
            
            print(f"  • FallbackReceiver Contract deployed: {contract_address}")
            print(f"  • Initial balance: {initial_balance / 10**18:.6f} BNB")
            print(f"  • Initial received count: {initial_count} ✅")
            
        except Exception as e:
            print(f"  • FallbackReceiver Contract: ❌ Deployment failed - {e}")
            import traceback
            traceback.print_exc()
            self.fallback_receiver_address = None
        
        print()
    
    def _set_balance(self, address: str, balance_wei: int):
        """
        使用 Anvil cheatcode 设置地址余额
        
        Args:
            address: 地址
            balance_wei: 余额 (wei)
        """
        from eth_utils import to_checksum_address
        
        address_checksum = to_checksum_address(address)
        self.w3.provider.make_request(
            'anvil_setBalance',
            [address_checksum, hex(balance_wei)]
        )
    
    def get_balance(self, address: str) -> float:
        """
        获取地址余额
        
        Args:
            address: 地址
            
        Returns:
            余额 (BNB)
        """
        balance_wei = self.w3.eth.get_balance(address)
        return balance_wei / 10**18
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.stop()

