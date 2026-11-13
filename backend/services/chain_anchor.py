"""
Optional public-chain anchoring.

When CHAIN_RPC_URL, CHAIN_PRIVATE_KEY and CHAIN_CONTRACT_ADDRESS are set (and
`web3` is installed), POST /ledger/anchor commits the Merkle root of every
not-yet-anchored ledger block to the TransFundEscrow contract on an EVM chain
(e.g. Polygon Amoy testnet). Without them the platform still runs on its
internal hash chain and reports anchoring as disabled.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

import models
from services.ledger import merkle_root

ABI_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "contracts", "TransFundEscrow.json")


def _env() -> dict[str, str | None]:
    return {
        "rpc": os.getenv("CHAIN_RPC_URL"),
        "key": os.getenv("CHAIN_PRIVATE_KEY"),
        "address": os.getenv("CHAIN_CONTRACT_ADDRESS"),
        "network": os.getenv("CHAIN_NETWORK_NAME", "evm"),
        "explorer": os.getenv("CHAIN_EXPLORER_TX_URL"),  # e.g. https://amoy.polygonscan.com/tx/
    }


def status() -> dict[str, Any]:
    env = _env()
    configured = bool(env["rpc"] and env["key"] and env["address"])
    try:
        import web3  # noqa: F401
        has_web3 = True
    except ImportError:
        has_web3 = False
    return {
        "enabled": configured and has_web3,
        "configured": configured,
        "web3_installed": has_web3,
        "network": env["network"] if configured else None,
        "contract_address": env["address"] if configured else None,
        "explorer_tx_url": env["explorer"],
    }


@lru_cache(maxsize=1)
def _abi() -> list:
    with open(ABI_PATH) as f:
        return json.load(f)["abi"]


def _send_anchor(root_hex: str, from_block: int, to_block: int) -> str:
    from web3 import Web3

    env = _env()
    w3 = Web3(Web3.HTTPProvider(env["rpc"], request_kwargs={"timeout": 30}))
    account = w3.eth.account.from_key(env["key"])
    contract = w3.eth.contract(address=Web3.to_checksum_address(env["address"]), abi=_abi())
    tx = contract.functions.anchor(bytes.fromhex(root_hex), from_block, to_block).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": w3.eth.chain_id,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        raise RuntimeError("anchor transaction reverted")
    return tx_hash.hex()


def anchor_pending(db: Session) -> dict[str, Any]:
    st = status()
    if not st["enabled"]:
        raise RuntimeError(
            "Public-chain anchoring is not configured. Set CHAIN_RPC_URL, CHAIN_PRIVATE_KEY and "
            "CHAIN_CONTRACT_ADDRESS (and pip install web3) to enable it."
        )
    last = db.query(models.LedgerAnchor).order_by(models.LedgerAnchor.id.desc()).first()
    start = (last.to_block + 1) if last else 0
    blocks = (
        db.query(models.LedgerBlock)
        .filter(models.LedgerBlock.id >= start)
        .order_by(models.LedgerBlock.id.asc())
        .all()
    )
    if not blocks:
        return {"anchored": False, "message": "Nothing new to anchor"}

    root = merkle_root([b.block_hash for b in blocks])
    tx_hash = _send_anchor(root, blocks[0].id, blocks[-1].id)
    anchor = models.LedgerAnchor(
        from_block=blocks[0].id, to_block=blocks[-1].id, merkle_root=root,
        network=st["network"], tx_hash=tx_hash,
    )
    db.add(anchor)
    db.flush()
    for b in blocks:
        b.anchor_id = anchor.id
    db.commit()
    return {
        "anchored": True, "anchor_id": anchor.id, "from_block": anchor.from_block,
        "to_block": anchor.to_block, "merkle_root": root, "tx_hash": tx_hash, "network": anchor.network,
    }
