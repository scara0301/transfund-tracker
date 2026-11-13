"""
Deploy TransFundEscrow to an EVM chain.

    pip install web3
    CHAIN_RPC_URL=https://rpc-amoy.polygon.technology \
    CHAIN_PRIVATE_KEY=0x... \
    python contracts/deploy.py

Prints the contract address to put in backend/.env as CHAIN_CONTRACT_ADDRESS.
Re-compile after editing the .sol file with:  python contracts/compile.py
"""
import json
import os

from web3 import Web3

here = os.path.dirname(__file__)
artifact = json.load(open(os.path.join(here, "TransFundEscrow.json")))

w3 = Web3(Web3.HTTPProvider(os.environ["CHAIN_RPC_URL"]))
acct = w3.eth.account.from_key(os.environ["CHAIN_PRIVATE_KEY"])
Contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
tx = Contract.constructor().build_transaction({
    "from": acct.address,
    "nonce": w3.eth.get_transaction_count(acct.address),
    "chainId": w3.eth.chain_id,
})
tx_hash = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
print("TransFundEscrow deployed at", receipt.contractAddress)
print("tx:", tx_hash.hex())
