# TransFundEscrow

On-chain transparency layer for TransFund. Rupees move over Razorpay/UPI, so the
contract holds no money; the backend acts as an oracle and the contract enforces
the rules that matter to donors:

- milestones release strictly in order, and their total can't exceed the goal
- release requires donor approval weighted by contribution, with a quorum or an expired voting window
- cumulative releases ≤ raised, recorded expenses ≤ released
- `anchor(root, from, to)` commits Merkle roots of the backend ledger in contiguous ranges

The backend currently calls `anchor` (via `POST /ledger/anchor`). The escrow functions
mirror the backend's off-chain rules and are covered by the tests, ready for full mirroring.

```bash
pip install py-solc-x web3 "eth-tester[py-evm]" pytest
python contracts/compile.py          # .sol → TransFundEscrow.json
pytest contracts/test_escrow.py      # 9 tests on an in-process EVM
CHAIN_RPC_URL=... CHAIN_PRIVATE_KEY=0x... python contracts/deploy.py
```

Put the printed address in `backend/.env` as `CHAIN_CONTRACT_ADDRESS`. Use a testnet
(e.g. Polygon Amoy) and a dedicated key with only test funds.
