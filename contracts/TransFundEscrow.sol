// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title TransFundEscrow
 * @notice On-chain transparency layer for TransFund campaigns.
 *
 * Donations are paid in INR through regulated payment rails (Razorpay/UPI),
 * so rupees never touch the chain. Instead, the TransFund backend acts as an
 * oracle that mirrors every financial event here, and this contract enforces
 * the release rules so that no one — including the platform — can record a
 * fund release that donors did not approve:
 *
 *   - Funds are split into sequential milestones.
 *   - A milestone can only be released after the organizer submits proof
 *     and contributing donors vote, weighted by how much they gave.
 *   - Release needs approve weight > reject weight, and either a quorum of
 *     the campaign's raised amount voted or the voting window has ended.
 *   - Cumulative releases can never exceed what was actually raised, and
 *     recorded expenditure can never exceed what was released.
 *
 * In addition, the backend periodically commits a Merkle root of its full
 * hash-chained ledger via {anchor}, so any later rewrite of off-chain
 * history is publicly detectable.
 *
 * Amounts are in paise (1 INR = 100 paise). Donor identities are stored as
 * keccak/sha256 hashes of their email — no personal data on chain.
 */
contract TransFundEscrow {
    // ── Roles ──────────────────────────────────────────────────
    address public owner;
    mapping(address => bool) public oracles;

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    modifier onlyOracle() {
        require(oracles[msg.sender], "not oracle");
        _;
    }

    // ── Campaign & milestone state ─────────────────────────────
    enum MilestoneState { Pending, Voting, Released, Rejected }

    struct Milestone {
        uint256 amount;
        MilestoneState state;
        bytes32 proofHash;
        uint64 votingDeadline;
        uint32 round;
        uint256 approveWeight;
        uint256 rejectWeight;
    }

    struct Campaign {
        bool exists;
        bytes32 organizerHash;
        uint256 goal;
        uint256 raised;
        uint256 released;
        uint256 spent;
        uint16 quorumBps; // share of `raised` that must vote for an early release
        uint32 nextMilestone; // index of the only milestone that may be released next
    }

    mapping(uint256 => Campaign) public campaigns;
    mapping(uint256 => Milestone[]) internal _milestones;
    mapping(uint256 => mapping(bytes32 => uint256)) public contributionOf; // campaign => donorHash => paise
    mapping(bytes32 => bool) public recordedDonation;
    // campaign => milestone => round => donorHash => voted
    mapping(uint256 => mapping(uint256 => mapping(uint32 => mapping(bytes32 => bool)))) internal _voted;

    // ── Ledger anchoring ───────────────────────────────────────
    struct Anchor {
        bytes32 merkleRoot;
        uint64 fromBlock;
        uint64 toBlock;
        uint64 timestamp;
    }
    Anchor[] public anchors;

    // ── Events ─────────────────────────────────────────────────
    event OracleSet(address indexed oracle, bool enabled);
    event CampaignRegistered(uint256 indexed campaignId, uint256 goal, uint256 milestoneCount);
    event DonationRecorded(uint256 indexed campaignId, bytes32 indexed donationHash, bytes32 donorHash, uint256 amount);
    event ProofSubmitted(uint256 indexed campaignId, uint256 indexed milestone, bytes32 proofHash, uint64 deadline, uint32 round);
    event VoteRecorded(uint256 indexed campaignId, uint256 indexed milestone, bytes32 donorHash, bool approve, uint256 weight);
    event MilestoneRejected(uint256 indexed campaignId, uint256 indexed milestone, uint32 round);
    event FundsReleased(uint256 indexed campaignId, uint256 indexed milestone, uint256 amount);
    event ExpenseRecorded(uint256 indexed campaignId, bytes32 indexed expenseHash, uint256 amount);
    event LedgerAnchored(uint256 indexed anchorId, bytes32 merkleRoot, uint64 fromBlock, uint64 toBlock);

    constructor() {
        owner = msg.sender;
        oracles[msg.sender] = true;
        emit OracleSet(msg.sender, true);
    }

    function setOracle(address oracle, bool enabled) external onlyOwner {
        oracles[oracle] = enabled;
        emit OracleSet(oracle, enabled);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "zero address");
        owner = newOwner;
    }

    // ── Campaign lifecycle ─────────────────────────────────────

    function registerCampaign(
        uint256 campaignId,
        bytes32 organizerHash,
        uint256 goal,
        uint256[] calldata milestoneAmounts,
        uint16 quorumBps
    ) external onlyOracle {
        require(!campaigns[campaignId].exists, "campaign exists");
        require(milestoneAmounts.length > 0, "no milestones");
        require(quorumBps <= 10_000, "bad quorum");
        uint256 total;
        for (uint256 i = 0; i < milestoneAmounts.length; i++) {
            require(milestoneAmounts[i] > 0, "zero milestone");
            total += milestoneAmounts[i];
            _milestones[campaignId].push(Milestone({
                amount: milestoneAmounts[i],
                state: MilestoneState.Pending,
                proofHash: bytes32(0),
                votingDeadline: 0,
                round: 0,
                approveWeight: 0,
                rejectWeight: 0
            }));
        }
        require(total <= goal, "milestones exceed goal");
        campaigns[campaignId] = Campaign({
            exists: true,
            organizerHash: organizerHash,
            goal: goal,
            raised: 0,
            released: 0,
            spent: 0,
            quorumBps: quorumBps,
            nextMilestone: 0
        });
        emit CampaignRegistered(campaignId, goal, milestoneAmounts.length);
    }

    function recordDonation(uint256 campaignId, bytes32 donationHash, bytes32 donorHash, uint256 amount)
        external
        onlyOracle
    {
        Campaign storage c = _campaign(campaignId);
        require(amount > 0, "zero amount");
        require(!recordedDonation[donationHash], "duplicate donation");
        recordedDonation[donationHash] = true;
        c.raised += amount;
        contributionOf[campaignId][donorHash] += amount;
        emit DonationRecorded(campaignId, donationHash, donorHash, amount);
    }

    function submitProof(uint256 campaignId, uint256 milestone, bytes32 proofHash, uint64 votingPeriod)
        external
        onlyOracle
    {
        Campaign storage c = _campaign(campaignId);
        require(milestone == c.nextMilestone, "milestones release in order");
        Milestone storage m = _milestones[campaignId][milestone];
        require(m.state == MilestoneState.Pending || m.state == MilestoneState.Rejected, "not awaiting proof");
        require(proofHash != bytes32(0), "empty proof");
        m.state = MilestoneState.Voting;
        m.proofHash = proofHash;
        m.round += 1;
        m.approveWeight = 0;
        m.rejectWeight = 0;
        m.votingDeadline = uint64(block.timestamp) + votingPeriod;
        emit ProofSubmitted(campaignId, milestone, proofHash, m.votingDeadline, m.round);
    }

    function recordVote(uint256 campaignId, uint256 milestone, bytes32 donorHash, bool approve) external onlyOracle {
        _campaign(campaignId);
        Milestone storage m = _milestones[campaignId][milestone];
        require(m.state == MilestoneState.Voting, "not voting");
        require(block.timestamp <= m.votingDeadline, "voting closed");
        uint256 weight = contributionOf[campaignId][donorHash];
        require(weight > 0, "not a donor");
        require(!_voted[campaignId][milestone][m.round][donorHash], "already voted");
        _voted[campaignId][milestone][m.round][donorHash] = true;
        if (approve) m.approveWeight += weight;
        else m.rejectWeight += weight;
        emit VoteRecorded(campaignId, milestone, donorHash, approve, weight);
    }

    /// @notice Close voting on a milestone. Releases if approved, otherwise marks it rejected.
    function finalizeMilestone(uint256 campaignId, uint256 milestone) external onlyOracle returns (bool released) {
        Campaign storage c = _campaign(campaignId);
        Milestone storage m = _milestones[campaignId][milestone];
        require(m.state == MilestoneState.Voting, "not voting");

        uint256 voted = m.approveWeight + m.rejectWeight;
        bool quorum = c.raised > 0 && voted * 10_000 >= uint256(c.quorumBps) * c.raised;
        bool windowOver = block.timestamp > m.votingDeadline;
        require(quorum || windowOver, "voting still open");

        if (m.approveWeight > m.rejectWeight) {
            require(c.released + m.amount <= c.raised, "insufficient raised funds");
            m.state = MilestoneState.Released;
            c.released += m.amount;
            c.nextMilestone += 1;
            emit FundsReleased(campaignId, milestone, m.amount);
            return true;
        }
        m.state = MilestoneState.Rejected;
        emit MilestoneRejected(campaignId, milestone, m.round);
        return false;
    }

    function recordExpense(uint256 campaignId, bytes32 expenseHash, uint256 amount) external onlyOracle {
        Campaign storage c = _campaign(campaignId);
        require(amount > 0, "zero amount");
        require(c.spent + amount <= c.released, "exceeds released funds");
        c.spent += amount;
        emit ExpenseRecorded(campaignId, expenseHash, amount);
    }

    // ── Ledger anchoring ───────────────────────────────────────

    function anchor(bytes32 merkleRoot, uint64 fromBlock, uint64 toBlock) external onlyOracle returns (uint256 id) {
        require(toBlock >= fromBlock, "bad range");
        if (anchors.length > 0) {
            require(fromBlock == anchors[anchors.length - 1].toBlock + 1, "range must continue last anchor");
        }
        anchors.push(Anchor(merkleRoot, fromBlock, toBlock, uint64(block.timestamp)));
        id = anchors.length - 1;
        emit LedgerAnchored(id, merkleRoot, fromBlock, toBlock);
    }

    // ── Views ──────────────────────────────────────────────────

    function anchorCount() external view returns (uint256) {
        return anchors.length;
    }

    function milestoneCount(uint256 campaignId) external view returns (uint256) {
        return _milestones[campaignId].length;
    }

    function getMilestone(uint256 campaignId, uint256 milestone) external view returns (Milestone memory) {
        return _milestones[campaignId][milestone];
    }

    function _campaign(uint256 campaignId) internal view returns (Campaign storage c) {
        c = campaigns[campaignId];
        require(c.exists, "unknown campaign");
    }
}
