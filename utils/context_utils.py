import streamlit as st


def sync_context():

    context = st.session_state.context

    context.source_system = (
        st.session_state.source_system
    )

    context.target_system = (
        st.session_state.target_system
    )

    context.source_entity = (
        st.session_state.source_entity
    )

    context.target_entity = (
        st.session_state.target_entity
    )

    context.source_schema = (
        st.session_state.source_schema
    )

    context.target_schema = (
        st.session_state.target_schema
    )

    context.prediction = (
        st.session_state.prediction
    )

    context.compatibility = (
        st.session_state.compatibility
    )

    context.report_bytes = st.session_state.report_bytes