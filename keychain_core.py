"""
KeyChain core logic: a minimal blockchain plus the rental rules.

No Streamlit here, so this file can be tested on its own.

Course concepts used:
- Lecture 1: SHA-256 hashes, hash pointers (each block stores the previous hash)
- Lecture 2: proof of work, double-spend prevention (= double booking)
- Lecture 4: tokenisation (each flat = a unique token), escrow smart contract
- Lecture 5: euro stablecoin (wallets hold EURC-like digital euros)
- Lecture 4 again: every node replays the whole chain to compute the current state
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime

DIFFICULTY = 3              # number of leading zeros required in a block hash
GENESIS_PREVIOUS_HASH = "0" * 64


# ---------------------------------------------------------------- helpers
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wallet_address(name: str) -> str:
    """A pseudo wallet address derived from the user's name."""
    return "0x" + sha256("keychain-wallet:" + name.strip().lower())[:16]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalise_address(address: str, city: str) -> str:
    text = f"{address} {city}".lower().replace(",", " ").replace("-", " ")
    return " ".join(text.split())


def months_between(start: str, end: str) -> list[str]:
    """['2026-09', '2026-10', ...] for a lease running from start to end."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    out, y, m = [], s.year, s.month
    while (y, m) <= (e.year, e.month):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


class ValidationError(Exception):
    """Raised when a transaction breaks a protocol rule. Nothing is written."""


# ---------------------------------------------------------------- blocks
@dataclass
class Block:
    index: int
    timestamp: str
    transactions: list
    previous_hash: str
    nonce: int = 0
    hash: str = ""

    def header(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
        }

    def compute_hash(self) -> str:
        return sha256(json.dumps(self.header(), sort_keys=True, ensure_ascii=False))

    def mine(self, difficulty: int = DIFFICULTY) -> None:
        """Proof of work: try nonces until the hash starts with `difficulty` zeros."""
        prefix = "0" * difficulty
        self.nonce = 0
        h = self.compute_hash()
        while not h.startswith(prefix):
            self.nonce += 1
            h = self.compute_hash()
        self.hash = h


# ---------------------------------------------------------------- rules
def empty_state() -> dict:
    return {
        "listings": {},   # listing_id -> dict
        "leases": {},     # lease_id -> dict
        "balances": {},   # name -> euros (EURC)
        "escrow": {},     # lease_id -> euros still locked in the escrow contract
        "students": [],   # names that topped up a wallet
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _eur(x: float) -> str:
    return f"{x:,.0f} €".replace(",", " ")


def _get_lease(s: dict, lease_id: str) -> dict:
    _require(lease_id in s["leases"], f"Unknown lease {lease_id}.")
    return s["leases"][lease_id]


def _fund(s, d):
    who, amount = d["who"].strip(), d["amount"]
    _require(who != "", "A wallet needs a name.")
    _require(amount > 0, "The top-up amount must be positive.")
    s["balances"][who] = s["balances"].get(who, 0) + amount
    if who not in s["students"]:
        s["students"].append(who)


def _mint_listing(s, d):
    owner, address, city = d["owner"].strip(), d["address"].strip(), d["city"].strip()
    rent, deposit, furnished = d["rent"], d["deposit"], d["furnished"]
    _require(owner != "", "The landlord's name is missing.")
    _require(address != "" and city != "", "The address and city are required.")
    _require(rent > 0, "The rent must be positive.")
    _require(deposit > 0, "The deposit must be positive.")
    cap = rent * (2 if furnished else 1)
    _require(
        deposit <= cap,
        f"Deposit of {_eur(deposit)} exceeds the legal cap of {_eur(cap)} "
        f"({'2 months of rent for a furnished' if furnished else '1 month of rent for an unfurnished'} "
        f"flat, French rental law of 1989).",
    )
    _require(d.get("proof_hash", "") != "",
             "No proof of ownership: the flat cannot be tokenised without one.")
    key = _normalise_address(address, city)
    for other in s["listings"].values():
        if other["key"] == key:
            if other["owner"] != owner:
                raise ValidationError(
                    f"This flat is already tokenised by {other['owner']} (token {other['id']}). "
                    f"A second person cannot list it: likely a fake listing."
                )
            raise ValidationError(f"This flat is already listed as {other['id']}.")
    lid = d["listing_id"]
    s["listings"][lid] = {
        "id": lid, "owner": owner, "address": address, "city": city,
        "rent": rent, "deposit": deposit, "furnished": furnished,
        "key": key, "proof_hash": d["proof_hash"],
        "token": sha256(f"{lid}|{key}|{owner}|{d['proof_hash']}"),
    }


def _book(s, d):
    lid, tenant = d["listing_id"], d["tenant"].strip()
    _require(lid in s["listings"], f"Unknown listing {lid}.")
    listing = s["listings"][lid]
    _require(tenant != "", "The tenant's name is missing.")
    _require(tenant != listing["owner"], "A landlord cannot rent their own flat.")
    start, end = date.fromisoformat(d["start"]), date.fromisoformat(d["end"])
    _require(start < end, "The lease must end after it starts.")
    # Double-booking rule = the double-spend rule of Lecture 2
    for other in s["leases"].values():
        if other["listing_id"] != lid:
            continue
        o_start, o_end = date.fromisoformat(other["start"]), date.fromisoformat(other["end"])
        if start < o_end and o_start < end:
            raise ValidationError(
                f"Double booking blocked: {listing['address']} is already booked by "
                f"{other['tenant']} from {other['start']} to {other['end']}. "
                f"One token, one tenant per period."
            )
    deposit = listing["deposit"]
    balance = s["balances"].get(tenant, 0)
    _require(balance >= deposit,
             f"{tenant} has {_eur(balance)} but the deposit is {_eur(deposit)}.")
    s["balances"][tenant] = balance - deposit
    s["escrow"][d["lease_id"]] = deposit
    s["leases"][d["lease_id"]] = {
        "id": d["lease_id"], "listing_id": lid, "tenant": tenant,
        "landlord": listing["owner"], "start": d["start"], "end": d["end"],
        "rent": listing["rent"], "deposit": deposit, "status": "ACTIVE",
        "checkin_hash": None, "checkout_hash": None, "payments": [],
        "claim": None, "refunded_to_tenant": 0, "paid_to_landlord": 0,
    }


def _checkin(s, d):
    lease = _get_lease(s, d["lease_id"])
    _require(lease["status"] == "ACTIVE", "Check-in is only possible on an active lease.")
    _require(lease["checkin_hash"] is None, "The check-in report is already recorded.")
    lease["checkin_hash"] = d["report_hash"]


def _pay_rent(s, d):
    lease = _get_lease(s, d["lease_id"])
    _require(lease["status"] == "ACTIVE", "Rent can only be paid on an active lease.")
    month = d["month"]
    _require(month in months_between(lease["start"], lease["end"]),
             f"{month} is outside the lease period.")
    _require(month not in lease["payments"], f"Rent for {month} is already paid.")
    tenant, rent = lease["tenant"], lease["rent"]
    balance = s["balances"].get(tenant, 0)
    _require(balance >= rent, f"{tenant} has {_eur(balance)}, rent is {_eur(rent)}.")
    s["balances"][tenant] = balance - rent
    s["balances"][lease["landlord"]] = s["balances"].get(lease["landlord"], 0) + rent
    lease["payments"].append(month)


def _checkout(s, d):
    lease = _get_lease(s, d["lease_id"])
    _require(lease["status"] == "ACTIVE", "Only an active lease can be checked out.")
    lease["checkout_hash"] = d["report_hash"]
    lease["status"] = "ENDED"


def _release(s, lease, to_tenant, to_landlord):
    s["balances"][lease["tenant"]] = s["balances"].get(lease["tenant"], 0) + to_tenant
    s["balances"][lease["landlord"]] = s["balances"].get(lease["landlord"], 0) + to_landlord
    lease["refunded_to_tenant"] += to_tenant
    lease["paid_to_landlord"] += to_landlord
    s["escrow"][lease["id"]] -= to_tenant + to_landlord


def _claim(s, d):
    lease = _get_lease(s, d["lease_id"])
    _require(lease["status"] == "ENDED",
             "A claim can only be filed after check-out and before the deadline.")
    locked = s["escrow"][lease["id"]]
    amount = d["amount"]
    _require(0 < amount <= locked, f"The claim must be between 1 € and {_eur(locked)}.")
    _require(d["reason"].strip() != "", "A claim needs a reason.")
    # Only the contested amount stays frozen; the rest goes back at once
    _release(s, lease, to_tenant=locked - amount, to_landlord=0)
    lease["claim"] = {"amount": amount, "reason": d["reason"].strip()}
    lease["status"] = "DISPUTE"


def _resolve(s, d):
    lease = _get_lease(s, d["lease_id"])
    _require(lease["status"] == "DISPUTE", "There is no open dispute on this lease.")
    frozen = s["escrow"][lease["id"]]
    award = d["to_landlord"]
    _require(0 <= award <= frozen, f"The award must be between 0 € and {_eur(frozen)}.")
    _release(s, lease, to_tenant=frozen - award, to_landlord=award)
    lease["status"] = "CLOSED"


def _auto_release(s, d):
    lease = _get_lease(s, d["lease_id"])
    _require(lease["status"] == "ENDED",
             "Automatic refund applies only to a checked-out lease with no claim.")
    _release(s, lease, to_tenant=s["escrow"][lease["id"]], to_landlord=0)
    lease["status"] = "CLOSED"


HANDLERS = {
    "FUND": _fund,
    "MINT_LISTING": _mint_listing,
    "BOOK": _book,
    "CHECK_IN": _checkin,
    "PAY_RENT": _pay_rent,
    "CHECK_OUT": _checkout,
    "CLAIM": _claim,
    "RESOLVE": _resolve,
    "AUTO_RELEASE": _auto_release,
}


def apply_tx(state: dict, tx: dict) -> None:
    handler = HANDLERS.get(tx["type"])
    _require(handler is not None, f"Unknown transaction type {tx['type']}.")
    handler(state, tx["data"])


# ---------------------------------------------------------------- ledger
class KeyChainLedger:
    def __init__(self, difficulty: int = DIFFICULTY):
        self.difficulty = difficulty
        genesis = Block(0, now_iso(),
                        [{"type": "GENESIS", "data": {"message": "KeyChain genesis block"}}],
                        GENESIS_PREVIOUS_HASH)
        genesis.mine(difficulty)
        self.chain: list[Block] = [genesis]
        self._backup = None   # (block index, original transactions) after a tamper

    # --- integrity -------------------------------------------------------
    def validate(self) -> list[dict]:
        """Every node re-checks every block. Returns the problems found."""
        problems, prefix = [], "0" * self.difficulty
        for i, b in enumerate(self.chain):
            if b.compute_hash() != b.hash:
                problems.append({"index": i, "reason":
                                 "Content changed: the stored hash no longer matches the block."})
            elif not b.hash.startswith(prefix):
                problems.append({"index": i, "reason": "Missing proof of work."})
            if i > 0 and b.previous_hash != self.chain[i - 1].hash:
                problems.append({"index": i, "reason": "Broken link to the previous block."})
        return problems

    def is_valid(self) -> bool:
        return not self.validate()

    # --- state = replay of the whole chain --------------------------------
    def state(self) -> dict:
        s = empty_state()
        for b in self.chain[1:]:
            for tx in b.transactions:
                try:
                    apply_tx(s, copy.deepcopy(tx))
                except ValidationError:
                    continue   # only possible on a tampered chain
        return s

    def next_id(self, prefix: str, kind: str) -> str:
        return f"{prefix}{len(self.state()[kind]) + 1:03d}"

    # --- writing ----------------------------------------------------------
    def submit(self, tx_type: str, data: dict) -> Block:
        if not self.is_valid():
            raise ValidationError(
                "Chain integrity check failed: a past block was altered. "
                "Nodes refuse new transactions until the honest chain is restored."
            )
        tx = {"type": tx_type, "data": data, "timestamp": now_iso()}
        apply_tx(self.state(), copy.deepcopy(tx))       # raises if a rule is broken
        block = Block(len(self.chain), now_iso(), [tx], self.chain[-1].hash)
        block.mine(self.difficulty)
        self.chain.append(block)
        return block

    # --- fraud demo: rewrite history ----------------------------------------
    def fund_block_indices(self) -> list[int]:
        return [b.index for b in self.chain if b.transactions[0]["type"] == "FUND"]

    def tamper(self, block_index: int, new_amount: int) -> None:
        if self._backup is None:
            self._backup = (block_index, copy.deepcopy(self.chain[block_index].transactions))
        self.chain[block_index].transactions[0]["data"]["amount"] = new_amount

    def restore(self) -> None:
        if self._backup is not None:
            i, txs = self._backup
            self.chain[i].transactions = txs
            self._backup = None

    @property
    def tampered(self) -> bool:
        return self._backup is not None


# ---------------------------------------------------------------- demo data
def seed_demo(ledger: KeyChainLedger) -> None:
    """Pre-load a few wallets, flats and leases so the demo starts mid-story."""
    for name, amount in [("Léa", 6000), ("Hugo", 2500), ("Sara", 2500)]:
        ledger.submit("FUND", {"who": name, "amount": amount})
    flats = [
        ("Mme Martin", "12 rue de Vesle", "Reims", 550, True, 1100, "Title deed RE-2019-04412"),
        ("M. Dubois", "8 place du Vieux-Marché", "Rouen", 480, False, 480, "Title deed RO-2016-11873"),
        ("Mme Martin", "3 rue Talleyrand", "Reims", 620, True, 1240, "Title deed RE-2022-00951"),
    ]
    for owner, address, city, rent, furnished, deposit, proof in flats:
        ledger.submit("MINT_LISTING", {
            "listing_id": ledger.next_id("L", "listings"), "owner": owner,
            "address": address, "city": city, "rent": rent, "furnished": furnished,
            "deposit": deposit, "proof_hash": sha256(proof),
        })
    ledger.submit("BOOK", {"lease_id": "B001", "listing_id": "L001", "tenant": "Léa",
                           "start": "2026-09-01", "end": "2027-06-30"})
    ledger.submit("CHECK_IN", {"lease_id": "B001",
                               "report_hash": sha256("Check-in report B001: flat clean, 12 photos")})
    for month in ["2026-09", "2026-10", "2026-11"]:
        ledger.submit("PAY_RENT", {"lease_id": "B001", "month": month})
    ledger.submit("BOOK", {"lease_id": "B002", "listing_id": "L002", "tenant": "Hugo",
                           "start": "2025-09-01", "end": "2026-06-30"})
    ledger.submit("CHECK_IN", {"lease_id": "B002",
                               "report_hash": sha256("Check-in report B002: good condition, 9 photos")})
