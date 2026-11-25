"""
KeyChain – live prototype (Streamlit)

Run locally:   pip install -r requirements.txt
               streamlit run app.py
"""
from datetime import date

import pandas as pd
import streamlit as st

from keychain_core import (
    DIFFICULTY,
    KeyChainLedger,
    ValidationError,
    months_between,
    seed_demo,
    sha256,
    sha256_bytes,
    wallet_address,
)

st.set_page_config(page_title="KeyChain – Live demo", page_icon="🔑", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem;}
      .kc-hash {font-family: monospace; font-size: 0.85rem; color: #B9541F; word-break: break-all;}
      .kc-card {background: #FFFDF9; border: 1px solid #E3DCCF; border-radius: 14px; padding: 1rem 1.2rem; margin-bottom: 0.8rem;}
      .kc-tag {display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 600;}
      .kc-ACTIVE {background: #DDEBFF; color: #1D4E89;}
      .kc-ENDED {background: #FFF1D6; color: #8A5A00;}
      .kc-DISPUTE {background: #FBE0D3; color: #9A3B12;}
      .kc-CLOSED {background: #DDF3E4; color: #1E6B3A;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------ state
def get_ledger() -> KeyChainLedger:
    if "ledger" not in st.session_state:
        ledger = KeyChainLedger()
        seed_demo(ledger)
        st.session_state.ledger = ledger
    return st.session_state.ledger


ledger = get_ledger()
state = ledger.state()


def eur(x) -> str:
    return f"{x:,.0f} €".replace(",", " ")


def submit(tx_type: str, data: dict, success: str) -> None:
    """Send a transaction to the network. Shows the rejection inline, or reruns on success."""
    try:
        block = ledger.submit(tx_type, data)
    except ValidationError as e:
        st.error(f"❌ **Transaction rejected.** {e}")
        return
    st.session_state.flash = (
        f"✅ {success} Recorded in block #{block.index} · hash `{block.hash[:20]}…` "
        f"· proof of work found after {block.nonce:,} tries."
    )
    st.rerun()


def status_tag(status: str) -> str:
    return f'<span class="kc-tag kc-{status}">{status}</span>'


def listing_label(lid: str) -> str:
    l = state["listings"][lid]
    return f"{lid} · {l['address']}, {l['city']} · {eur(l['rent'])}/month"


def lease_label(bid: str) -> str:
    b = state["leases"][bid]
    l = state["listings"][b["listing_id"]]
    return f"{bid} · {b['tenant']} · {l['address']} ({b['status']})"


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("🔑 KeyChain")
    st.caption("Prototype for the Fintech & Blockchain course. "
               "The blockchain is simulated in Python; payments use digital euros (EURC).")
    st.subheader("Wallets")
    wallets = pd.DataFrame(
        [{"Name": n, "Address": wallet_address(n), "Balance": eur(v)}
         for n, v in state["balances"].items()]
    )
    st.dataframe(wallets, hide_index=True)
    st.subheader("Network")
    st.write(f"Proof of work: hashes must start with **{'0' * DIFFICULTY}**")
    st.write(f"Blocks: **{len(ledger.chain)}**")
    if st.button("↺ Reset the demo"):
        del st.session_state["ledger"]
        st.session_state.pop("flash", None)
        st.rerun()


# ------------------------------------------------------------------ header
st.title("🔑 KeyChain")
st.markdown("##### Student rentals without scams or lost deposits — live prototype")

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

problems = ledger.validate()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Blocks on the chain", len(ledger.chain))
m2.metric("Verified flats", len(state["listings"]))
m3.metric("Deposits in escrow", eur(sum(state["escrow"].values())))
m4.metric("Chain status", "✅ Valid" if not problems else "❌ Tampered")

tab_landlord, tab_student, tab_fraud, tab_moveout, tab_explorer = st.tabs(
    ["🏠 Landlord", "🎓 Student", "🚨 Fraud lab", "📦 Move-out", "⛓️ Block explorer"]
)

# ================================================================== LANDLORD
with tab_landlord:
    st.subheader("List a flat: it becomes a unique, verified token")
    with st.form("mint_form"):
        c1, c2 = st.columns(2)
        with c1:
            owner = st.text_input("Landlord", "Mme Martin")
            address = st.text_input("Street address", "27 boulevard Pasteur")
            city = st.text_input("City", "Reims")
            proof = st.text_input("Proof of ownership (title-deed reference)", "Title deed RE-2021-08817")
        with c2:
            rent = st.number_input("Monthly rent (€)", min_value=100, max_value=5000, value=520, step=10)
            furnished = st.checkbox("Furnished", value=True)
            deposit = st.number_input("Security deposit (€)", min_value=0, max_value=10000, value=1040, step=10)
            st.caption("Legal cap: 1 month of rent if unfurnished, 2 months if furnished. "
                       "The protocol rejects anything above.")
        minted = st.form_submit_button("🪙 Tokenise this flat", type="primary")
    if minted:
        submit("MINT_LISTING", {
            "listing_id": ledger.next_id("L", "listings"),
            "owner": owner, "address": address, "city": city,
            "rent": int(rent), "furnished": bool(furnished), "deposit": int(deposit),
            "proof_hash": sha256(proof) if proof.strip() else "",
        }, f"Flat tokenised: {address}, {city}.")

    st.subheader("Verified flats on KeyChain")
    rows = []
    for l in state["listings"].values():
        booked = [b for b in state["leases"].values() if b["listing_id"] == l["id"]]
        rows.append({
            "Token": l["id"], "Address": l["address"], "City": l["city"],
            "Rent": eur(l["rent"]), "Deposit": eur(l["deposit"]),
            "Furnished": "Yes" if l["furnished"] else "No", "Landlord": l["owner"],
            "Bookings": len(booked), "Token hash": l["token"][:16] + "…", "Verified": "✅",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True)

# ================================================================== STUDENT
with tab_student:
    students = state["students"]
    left, right = st.columns([1, 2])
    with left:
        st.subheader("Wallet")
        student = st.selectbox("Student", students, key="student_select")
        st.metric("Balance (digital euros)", eur(state["balances"].get(student, 0)))
        st.markdown(f'<div class="kc-hash">{wallet_address(student)}</div>', unsafe_allow_html=True)
        with st.expander("Top up the wallet (€ → EURC)"):
            top_up = st.number_input("Amount (€)", min_value=50, max_value=10000, value=500, step=50)
            if st.button("Top up", key="topup_btn"):
                submit("FUND", {"who": student, "amount": int(top_up)},
                       f"{eur(top_up)} added to {student}'s wallet.")
        with st.expander("New student"):
            new_name = st.text_input("Name", "Inès")
            if st.button("Create wallet with 3 000 €", key="new_student_btn"):
                submit("FUND", {"who": new_name, "amount": 3000}, f"Wallet created for {new_name}.")

    with right:
        st.subheader("Book a flat")
        lid = st.selectbox("Flat", list(state["listings"].keys()), format_func=listing_label,
                           key="book_listing")
        c1, c2 = st.columns(2)
        start = c1.date_input("Move-in", value=date(2027, 9, 1), key="book_start")
        end = c2.date_input("Move-out", value=date(2028, 6, 30), key="book_end")
        dep = state["listings"][lid]["deposit"]
        st.info(f"The deposit of **{eur(dep)}** will be locked in the escrow contract. "
                f"Nobody can touch it, not even the landlord.")
        if st.button("🔒 Book and lock the deposit", type="primary", key="book_btn"):
            submit("BOOK", {
                "lease_id": ledger.next_id("B", "leases"), "listing_id": lid,
                "tenant": student, "start": start.isoformat(), "end": end.isoformat(),
            }, f"{student} booked {state['listings'][lid]['address']}: {eur(dep)} locked in escrow.")

    st.divider()
    st.subheader(f"{student}'s leases")
    my_leases = [b for b in state["leases"].values() if b["tenant"] == student]
    if not my_leases:
        st.caption("No lease yet.")
    for b in my_leases:
        l = state["listings"][b["listing_id"]]
        st.markdown(
            f'<div class="kc-card"><b>{b["id"]} · {l["address"]}, {l["city"]}</b> '
            f'{status_tag(b["status"])}<br>{b["start"]} → {b["end"]} · rent {eur(b["rent"])} · '
            f'in escrow: <b>{eur(state["escrow"].get(b["id"], 0))}</b> · '
            f'rent paid: {", ".join(b["payments"]) or "none"}</div>',
            unsafe_allow_html=True,
        )
        if b["status"] != "ACTIVE":
            continue
        c1, c2 = st.columns(2)
        with c1:
            if b["checkin_hash"] is None:
                photo = st.file_uploader("Check-in photo", type=["png", "jpg", "jpeg"],
                                         key=f"ci_photo_{b['id']}")
                note = st.text_input("Check-in notes", "Flat clean, no damage",
                                     key=f"ci_note_{b['id']}")
                if st.button("📸 Record check-in", key=f"ci_btn_{b['id']}"):
                    content = photo.getvalue() if photo else note.encode()
                    submit("CHECK_IN", {"lease_id": b["id"], "report_hash": sha256_bytes(content)},
                           "Check-in report hashed and recorded.")
            else:
                st.caption("Check-in report fingerprint")
                st.markdown(f'<div class="kc-hash">{b["checkin_hash"]}</div>', unsafe_allow_html=True)
        with c2:
            unpaid = [m for m in months_between(b["start"], b["end"]) if m not in b["payments"]]
            if unpaid:
                month = st.selectbox("Month", unpaid, key=f"rent_month_{b['id']}")
                if st.button(f"💶 Pay rent ({eur(b['rent'])})", key=f"rent_btn_{b['id']}"):
                    submit("PAY_RENT", {"lease_id": b["id"], "month": month},
                           f"Rent for {month} paid to {b['landlord']}.")

# ================================================================== FRAUD LAB
with tab_fraud:
    st.subheader("Three ways to cheat, and why the protocol says no")
    f1, f2, f3 = st.columns(3)

    with f1:
        st.markdown("#### 1 · Double booking")
        st.caption("The double-spend problem of Lecture 2, applied to a flat.")
        target = next((b for b in state["leases"].values()
                       if b["status"] in ("ACTIVE", "ENDED", "DISPUTE")), None)
        if target is None:
            st.info("Book a flat first in the Student tab.")
        else:
            tl = state["listings"][target["listing_id"]]
            st.write(f"**{tl['address']}** is booked by **{target['tenant']}** "
                     f"from {target['start']} to {target['end']}.")
            others = [s for s in state["students"] if s != target["tenant"]]
            attacker = st.selectbox("Another student", others, key="fraud_attacker")
            if others and st.button("Try to book the same flat", key="fraud_double"):
                submit("BOOK", {
                    "lease_id": ledger.next_id("B", "leases"), "listing_id": target["listing_id"],
                    "tenant": attacker, "start": target["start"], "end": target["end"],
                }, "Booking accepted.")

    with f2:
        st.markdown("#### 2 · Fake listing")
        st.caption("A scammer copies a real ad and lists the flat as his own.")
        victim = state["listings"].get("L001") or next(iter(state["listings"].values()))
        st.write(f"Real flat: **{victim['address']}, {victim['city']}**, owned by {victim['owner']}.")
        if st.button("List it as 'Mr Scammer' at 350 €", key="fraud_fake"):
            submit("MINT_LISTING", {
                "listing_id": ledger.next_id("L", "listings"), "owner": "Mr Scammer",
                "address": victim["address"], "city": victim["city"], "rent": 350,
                "furnished": False, "deposit": 350, "proof_hash": sha256("forged deed"),
            }, "Listing accepted.")

    with f3:
        st.markdown("#### 3 · Rewrite history")
        st.caption("Someone edits an old block to give themselves money.")
        fund_blocks = ledger.fund_block_indices()
        if not ledger.tampered:
            idx = st.selectbox(
                "Block to edit", fund_blocks, key="fraud_block",
                format_func=lambda i: f"Block #{i} · top-up of "
                f"{ledger.chain[i].transactions[0]['data']['who']}",
            )
            if st.button("Change the amount to 50 000 €", key="fraud_tamper"):
                ledger.tamper(idx, 50000)
                st.rerun()
        else:
            for p in problems:
                st.error(f"Block #{p['index']}: {p['reason']}")
            st.write("Every node recomputes the hashes and sees the change. To cheat, the attacker "
                     "would have to redo the proof of work of this block **and every block after it**, "
                     "faster than the whole network.")
            if st.button("↺ Restore the honest chain", key="fraud_restore", type="primary"):
                ledger.restore()
                st.rerun()

# ================================================================== MOVE-OUT
with tab_moveout:
    st.subheader("End of lease: the escrow refunds the deposit automatically")
    lease_ids = list(state["leases"].keys())
    if not lease_ids:
        st.info("No lease yet.")
    else:
        open_ids = [i for i in lease_ids if state["leases"][i]["status"] != "CLOSED"]
        default = lease_ids.index(open_ids[-1]) if open_ids else 0
        bid = st.selectbox("Lease", lease_ids, index=default, format_func=lease_label,
                           key="moveout_lease")
        b = state["leases"][bid]
        locked = state["escrow"].get(bid, 0)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Deposit", eur(b["deposit"]))
        k2.metric("Still in escrow", eur(locked))
        k3.metric(f"Refunded to {b['tenant']}", eur(b["refunded_to_tenant"]))
        k4.metric(f"Paid to {b['landlord']}", eur(b["paid_to_landlord"]))
        st.markdown(f"Status: {status_tag(b['status'])}", unsafe_allow_html=True)

        if b["status"] == "ACTIVE":
            note = st.text_input("Move-out report", "Flat returned clean, keys handed over",
                                 key=f"co_note_{bid}")
            if st.button("🚪 Check out", type="primary", key=f"co_btn_{bid}"):
                submit("CHECK_OUT", {"lease_id": bid, "report_hash": sha256(note)},
                       "Check-out recorded. The landlord's claim window is open.")

        elif b["status"] == "ENDED":
            st.info("The claim window is open. With no claim before the deadline, "
                    "the deposit goes back to the student automatically.")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Scenario A · No claim**")
                if st.button("⏱️ Deadline passes with no claim", key=f"auto_{bid}"):
                    submit("AUTO_RELEASE", {"lease_id": bid},
                           f"{eur(locked)} refunded to {b['tenant']} automatically.")
            with c2:
                st.markdown("**Scenario B · The landlord files a claim**")
                amount = st.number_input("Amount claimed (€)", min_value=1, max_value=int(locked),
                                         value=min(150, int(locked)), step=10, key=f"claim_amt_{bid}")
                reason = st.text_input("Reason", "Stain on the carpet", key=f"claim_reason_{bid}")
                if st.button("⚖️ File the claim", key=f"claim_btn_{bid}"):
                    submit("CLAIM", {"lease_id": bid, "amount": int(amount), "reason": reason},
                           f"Claim filed: {eur(amount)} frozen, {eur(locked - amount)} "
                           f"refunded to {b['tenant']} straight away.")

        elif b["status"] == "DISPUTE":
            st.warning(f"Dispute: **{eur(locked)}** frozen ({b['claim']['reason']}). "
                       f"The rest was already refunded.")
            award = st.slider("Mediator's decision: amount awarded to the landlord (€)",
                              min_value=0, max_value=int(locked), value=int(locked) // 2,
                              step=10, key=f"award_{bid}")
            if st.button("Apply the decision", type="primary", key=f"resolve_{bid}"):
                submit("RESOLVE", {"lease_id": bid, "to_landlord": int(award)},
                       f"{eur(award)} to {b['landlord']}, {eur(locked - award)} to {b['tenant']}.")

        else:
            st.success(f"Closed. {b['tenant']} got back {eur(b['refunded_to_tenant'])}, "
                       f"{b['landlord']} received {eur(b['paid_to_landlord'])}.")

# ================================================================== EXPLORER
with tab_explorer:
    st.subheader("Block explorer")
    if problems:
        st.error("❌ Integrity check failed: " +
                 "; ".join(f"block #{p['index']}: {p['reason']}" for p in problems))
    else:
        st.success(f"✅ Chain valid: {len(ledger.chain)} blocks. Each hash starts with "
                   f"{'0' * DIFFICULTY} (proof of work) and points to the previous block.")

    with st.expander("🔬 Hash playground (Lecture 1)"):
        text = st.text_input("Type anything", "KeyChain", key="hash_text")
        st.markdown(f'<div class="kc-hash">{sha256(text)}</div>', unsafe_allow_html=True)
        st.caption("Change a single character: the whole fingerprint changes.")

    bad = {p["index"] for p in problems}
    for blk in reversed(ledger.chain):
        tx = blk.transactions[0]
        icon = "❌" if blk.index in bad else "🧱"
        with st.expander(f"{icon} Block #{blk.index} · {tx['type']} · {blk.hash[:16]}…",
                         expanded=blk.index == len(ledger.chain) - 1):
            c1, c2 = st.columns(2)
            c1.write(f"**Time:** {blk.timestamp}")
            c2.write(f"**Nonce:** {blk.nonce:,}")
            st.markdown(f'**Hash:** <span class="kc-hash">{blk.hash}</span>', unsafe_allow_html=True)
            st.markdown(f'**Previous hash:** <span class="kc-hash">{blk.previous_hash}</span>',
                        unsafe_allow_html=True)
            if blk.index in bad:
                st.markdown(f'**Recomputed hash:** <span class="kc-hash">{blk.compute_hash()}</span>',
                            unsafe_allow_html=True)
            st.json(blk.transactions)
