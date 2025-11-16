"""CSS animations and styles shared across Streamlit pages."""

REVEAL_ANIMATIONS_CSS = """
<style>
    @keyframes revealText {
        0% {
            clip-path: inset(0 100% 0 0);
        }
        100% {
            clip-path: inset(0 0% 0 0);
        }
    }

    .gold-shimmer {
        color: #ffffff;
        display: inline-block;
        clip-path: inset(0 100% 0 0);
        animation: revealText 1.5s ease-out forwards;
    }

    .silver-shimmer {
        color: #666;
        display: inline-block;
        clip-path: inset(0 100% 0 0);
        animation: revealText 1.5s ease-out 2s forwards;
    }
</style>
"""


def inject_reveal_animations() -> None:
    """Inject reveal animations into the active Streamlit page."""
    import streamlit as st

    st.markdown(REVEAL_ANIMATIONS_CSS, unsafe_allow_html=True)


