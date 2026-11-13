"""
Contract tests on an in-process EVM.
    pip install web3 "eth-tester[py-evm]" pytest
    pytest contracts/test_escrow.py
"""
import json
import os

import pytest
from eth_tester.exceptions import TransactionFailed
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider

ART = json.load(open(os.path.join(os.path.dirname(__file__), "TransFundEscrow.json")))
H = lambda s: Web3.keccak(text=s)  # noqa: E731
CID = 1
ALICE, BOB, CAROL = H("alice@x.in"), H("bob@x.in"), H("carol@x.in")


@pytest.fixture
def env():
    w3 = Web3(EthereumTesterProvider())
    owner, stranger = w3.eth.accounts[0], w3.eth.accounts[1]
    w3.eth.default_account = owner
    tx = w3.eth.contract(abi=ART["abi"], bytecode=ART["bytecode"]).constructor().transact()
    addr = w3.eth.get_transaction_receipt(tx).contractAddress
    c = w3.eth.contract(address=addr, abi=ART["abi"])
    # goal ₹1,00,000 split 40k/60k; 20% quorum
    c.functions.registerCampaign(CID, H("org@x.in"), 100_000_00, [40_000_00, 60_000_00], 2000).transact()
    return w3, c, stranger


def reverts(fn, msg):
    with pytest.raises((TransactionFailed, Exception)) as e:
        fn()
    assert msg in str(e.value), str(e.value)


def advance(w3, seconds):
    w3.provider.ethereum_tester.time_travel(w3.eth.get_block("latest").timestamp + seconds)
    w3.provider.ethereum_tester.mine_blocks(1)


def test_only_oracle_can_write(env):
    w3, c, stranger = env
    reverts(lambda: c.functions.recordDonation(CID, H("d1"), ALICE, 100).transact({"from": stranger}), "not oracle")
    reverts(lambda: c.functions.anchor(b"\x01" * 32, 0, 5).transact({"from": stranger}), "not oracle")


def test_milestones_cannot_exceed_goal(env):
    _, c, _ = env
    reverts(lambda: c.functions.registerCampaign(2, H("o"), 100, [60, 50], 2000).transact(), "milestones exceed goal")


def test_duplicate_donation_rejected(env):
    _, c, _ = env
    c.functions.recordDonation(CID, H("d1"), ALICE, 100).transact()
    reverts(lambda: c.functions.recordDonation(CID, H("d1"), ALICE, 100).transact(), "duplicate donation")


def test_full_release_flow_with_quorum(env):
    w3, c, _ = env
    c.functions.recordDonation(CID, H("d1"), ALICE, 30_000_00).transact()
    c.functions.recordDonation(CID, H("d2"), BOB, 20_000_00).transact()

    # milestone 2 cannot jump the queue
    reverts(lambda: c.functions.submitProof(CID, 1, H("proof"), 3 * 86400).transact(), "release in order")
    c.functions.submitProof(CID, 0, H("proof"), 3 * 86400).transact()

    # only donors vote, once each, weighted by contribution
    reverts(lambda: c.functions.recordVote(CID, 0, CAROL, True).transact(), "not a donor")
    c.functions.recordVote(CID, 0, ALICE, True).transact()
    reverts(lambda: c.functions.recordVote(CID, 0, ALICE, False).transact(), "already voted")
    c.functions.recordVote(CID, 0, BOB, False).transact()

    m = c.functions.getMilestone(CID, 0).call()
    assert m[5] == 30_000_00 and m[6] == 20_000_00  # approve / reject weight

    c.functions.finalizeMilestone(CID, 0).transact()  # quorum met (100% voted), approve > reject
    camp = c.functions.campaigns(CID).call()
    assert camp[4] == 40_000_00  # released
    assert c.functions.getMilestone(CID, 0).call()[1] == 2  # Released


def test_release_waits_for_quorum_or_deadline(env):
    w3, c, _ = env
    c.functions.recordDonation(CID, H("d1"), ALICE, 5_000_00).transact()
    c.functions.recordDonation(CID, H("d2"), BOB, 45_000_00).transact()
    c.functions.submitProof(CID, 0, H("p"), 3600).transact()
    c.functions.recordVote(CID, 0, ALICE, True).transact()  # 10% of raised < 20% quorum
    reverts(lambda: c.functions.finalizeMilestone(CID, 0).transact(), "voting still open")
    advance(w3, 3601)
    reverts(lambda: c.functions.recordVote(CID, 0, BOB, False).transact(), "voting closed")
    c.functions.finalizeMilestone(CID, 0).transact()  # window over; approve 5k > reject 0
    assert c.functions.getMilestone(CID, 0).call()[1] == 2


def test_rejection_then_resubmission(env):
    _, c, _ = env
    c.functions.recordDonation(CID, H("d1"), ALICE, 50_000_00).transact()
    c.functions.submitProof(CID, 0, H("bad proof"), 86400).transact()
    c.functions.recordVote(CID, 0, ALICE, False).transact()
    c.functions.finalizeMilestone(CID, 0).transact()
    assert c.functions.getMilestone(CID, 0).call()[1] == 3  # Rejected
    assert c.functions.campaigns(CID).call()[4] == 0
    # new round: tallies reset and the same donor may vote again
    c.functions.submitProof(CID, 0, H("better proof"), 86400).transact()
    c.functions.recordVote(CID, 0, ALICE, True).transact()
    c.functions.finalizeMilestone(CID, 0).transact()
    assert c.functions.getMilestone(CID, 0).call()[1] == 2


def test_cannot_release_more_than_raised(env):
    _, c, _ = env
    c.functions.recordDonation(CID, H("d1"), ALICE, 10_000_00).transact()  # milestone needs 40k
    c.functions.submitProof(CID, 0, H("p"), 86400).transact()
    c.functions.recordVote(CID, 0, ALICE, True).transact()
    reverts(lambda: c.functions.finalizeMilestone(CID, 0).transact(), "insufficient raised funds")


def test_expenses_capped_by_released(env):
    _, c, _ = env
    reverts(lambda: c.functions.recordExpense(CID, H("e0"), 1).transact(), "exceeds released funds")
    c.functions.recordDonation(CID, H("d1"), ALICE, 50_000_00).transact()
    c.functions.submitProof(CID, 0, H("p"), 86400).transact()
    c.functions.recordVote(CID, 0, ALICE, True).transact()
    c.functions.finalizeMilestone(CID, 0).transact()
    c.functions.recordExpense(CID, H("e1"), 39_000_00).transact()
    reverts(lambda: c.functions.recordExpense(CID, H("e2"), 2_000_00).transact(), "exceeds released funds")


def test_anchor_ranges_must_be_contiguous(env):
    _, c, _ = env
    c.functions.anchor(b"\x01" * 32, 0, 9).transact()
    reverts(lambda: c.functions.anchor(b"\x02" * 32, 12, 20).transact(), "continue last anchor")
    c.functions.anchor(b"\x02" * 32, 10, 20).transact()
    assert c.functions.anchorCount().call() == 2
    assert c.functions.anchors(1).call()[0] == b"\x02" * 32
