"""Streamlit UI — single-partner, single-company workflow."""

import streamlit as st
from .harmonic import get_company_employees
from .roster import load_job_reqs
from .matching import rank_matches
from .export import export_match
from .store import init_db, log_match

st.set_page_config(page_title="NEA Talent Placement", layout="wide")


def _match_key(employee_id: str, dest_id: str) -> str:
    return f"match_{employee_id}_{dest_id}"


def main() -> None:
    init_db()
    st.title("NEA Talent Placement")

    # --- Company input ---
    company_domain = st.text_input(
        "Portfolio company domain",
        placeholder="e.g. stripe.com",
        help="Harmonic will look up current employees for this domain.",
    )

    if not company_domain:
        st.info("Enter a company domain above to begin.")
        st.stop()

    # --- Load employees ---
    if "employees" not in st.session_state or st.session_state.get("loaded_company") != company_domain:
        with st.spinner(f"Fetching employees from Harmonic for {company_domain}…"):
            employees = get_company_employees(company_domain)
        if not employees:
            st.error(f"No employees found for **{company_domain}**. Check the domain or your Harmonic API key.")
            st.stop()
        st.session_state["employees"] = employees
        st.session_state["loaded_company"] = company_domain
        st.session_state["matches"] = {}

    employees = st.session_state["employees"]

    # --- Load job reqs ---
    destinations = load_job_reqs()
    if not destinations:
        st.warning(
            "No job reqs found. Add rows to `data/job_reqs.csv` "
            "(columns: company, role, description, contact_name, contact_email)."
        )

    st.caption(f"{len(employees)} employees · {len(destinations)} open roles")
    st.divider()

    # --- Main dashboard: one card per employee ---
    for emp in employees:
        with st.container(border=True):
            col1, col2 = st.columns([1, 3])

            with col1:
                badge = "🔑 Founder" if emp.is_founder else ("👔 Exec" if emp.is_executive else "")
                st.markdown(f"**{emp.name}** {badge}")
                st.caption(emp.title or "Unknown title")
                if emp.linkedin_url:
                    st.markdown(f"[LinkedIn]({emp.linkedin_url})")

            with col2:
                if not destinations:
                    st.caption("No job reqs loaded.")
                    continue

                # Score matches on demand
                if emp.id not in st.session_state["matches"]:
                    if st.button(f"Find matches", key=f"run_{emp.id}"):
                        with st.spinner("Scoring with Claude…"):
                            matches = rank_matches(emp, destinations, top_n=5)
                        st.session_state["matches"][emp.id] = matches
                        st.rerun()
                    continue

                matches = st.session_state["matches"][emp.id]
                if not matches:
                    st.caption("No matches found.")
                    continue

                for match in matches:
                    mkey = _match_key(emp.id, match.destination.id)
                    already_approved = st.session_state.get(f"approved_{mkey}", False)

                    mcol1, mcol2, mcol3 = st.columns([2, 3, 1])
                    with mcol1:
                        score_pct = int(match.score * 100)
                        color = "green" if score_pct >= 70 else ("orange" if score_pct >= 40 else "red")
                        st.markdown(
                            f"**{match.destination.role}** @ {match.destination.company}  \n"
                            f":{color}[{score_pct}% match]"
                        )
                    with mcol2:
                        st.caption(match.reasoning)
                        notes = st.text_input(
                            "Partner notes",
                            key=f"notes_{mkey}",
                            label_visibility="collapsed",
                            placeholder="Add notes (optional)",
                            disabled=already_approved,
                        )
                    with mcol3:
                        if already_approved:
                            st.success("Approved ✓")
                        else:
                            if st.button("Approve", key=f"approve_{mkey}"):
                                match.approved = True
                                match.partner_notes = notes or None
                                log_match(match)
                                path = export_match(match)
                                st.session_state[f"approved_{mkey}"] = True
                                st.toast(f"Exported to {path.name}")
                                st.rerun()

    # --- Sidebar: approved exports ---
    with st.sidebar:
        st.header("Approved matches")
        from .store import get_approved_matches
        approved = get_approved_matches()
        if not approved:
            st.caption("None yet.")
        for m in approved:
            st.markdown(f"**{m.employee.name}** → {m.destination.role} @ {m.destination.company}")
            if m.partner_notes:
                st.caption(m.partner_notes)


if __name__ == "__main__":
    main()
