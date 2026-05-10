"""Streamlit UI — single-partner, single-company workflow."""

import streamlit as st
from .harmonic import get_company_employees
from .roster import load_job_reqs
from .matching import rank_matches
from .export import export_match
from .store import init_db, log_match

st.set_page_config(page_title="NEA Talent Placement", layout="wide")


def main() -> None:
    init_db()
    st.title("NEA Talent Placement")

    # Section 1: key people
    ...

    # Section 2: matches
    ...

    # Section 3: approved exports
    ...


if __name__ == "__main__":
    main()
