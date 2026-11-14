"""Anchor the ledger's Merkle root into a real TransFundEscrow contract on an in-process EVM."""
import json
import os

import pytest

web3 = pytest.importorskip("web3")
pytest.importorskip("eth_tester")
from web3 import Web3  # noqa: E402
from web3.providers.eth_tester import EthereumTesterProvider  # noqa: E402

ART = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "contracts", "TransFundEscrow.json")))
KEY = "0x" + "00" * 31 + "01"  # eth-tester's first funded account


def test_anchor_commits_merkle_root_on_chain(client, campaign, monkeypatch):
    provider = EthereumTesterProvider()
    w3 = Web3(provider)
    acct = w3.eth.account.from_key(KEY)
    tx = w3.eth.contract(abi=ART["abi"], bytecode=ART["bytecode"]).constructor().transact({"from": acct.address})
    address = w3.eth.get_transaction_receipt(tx).contractAddress

    monkeypatch.setenv("CHAIN_RPC_URL", "http://eth-tester")
    monkeypatch.setenv("CHAIN_PRIVATE_KEY", KEY)
    monkeypatch.setenv("CHAIN_CONTRACT_ADDRESS", address)
    monkeypatch.setenv("CHAIN_NETWORK_NAME", "eth-tester")
    monkeypatch.setattr(Web3, "HTTPProvider", lambda *a, **k: provider)

    assert client.get("/ledger/status").json()["anchoring"]["enabled"] is True
    r = client.post("/ledger/anchor")
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["anchored"] and res["from_block"] == 0

    contract = w3.eth.contract(address=address, abi=ART["abi"])
    root, frm, to, _ts = contract.functions.anchors(0).call()
    assert root.hex() == res["merkle_root"] and (frm, to) == (res["from_block"], res["to_block"])

    # Recompute the Merkle root from the API's block list: anyone can do this check.
    from services.ledger import merkle_root
    blocks = client.get("/ledger/?limit=200").json()["blocks"]
    hashes = [b["block_hash"] for b in sorted(blocks, key=lambda b: b["index"]) if b["index"] <= to]
    assert merkle_root(hashes) == res["merkle_root"]

    # Next anchor continues the range; nothing new → no-op
    assert client.post("/ledger/anchor").json()["anchored"] is False
    v = client.get("/ledger/verify").json()
    assert v["valid"] and v["last_anchor"]["tx_hash"] == res["tx_hash"]
