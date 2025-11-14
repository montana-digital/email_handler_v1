"""CSS animations and styles for Email Butler."""

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
        /* Base text color - white */
        color: #ffffff;
        display: inline-block;
        clip-path: inset(0 100% 0 0);
        animation: revealText 1.5s ease-out forwards;
    }
    
    .silver-shimmer {
        /* Base text color - gray for subtitle */
        color: #666;
        display: inline-block;
        clip-path: inset(0 100% 0 0);
        animation: revealText 1.5s ease-out 2s forwards;
    }
</style>
"""


def inject_reveal_animations():
    """
    Inject CSS animations for left-to-right reveal effects into Streamlit page.
    
    This function should be called in the main() function to add
    reveal animations to the header text.
    
    The animations:
    - Play once on page load
    - Reveal text from left to right
    - "Email Butler" reveals immediately
    - "part of the SPEAR toolbelt" reveals 2 seconds later
    """
    import streamlit as st
    st.markdown(REVEAL_ANIMATIONS_CSS, unsafe_allow_html=True)



