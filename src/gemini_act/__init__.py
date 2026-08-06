"""Gemini Act — a Google ADK agent that takes actions from inside Google Chat."""

__version__ = "0.1.0"


def main() -> None:
    from gemini_act.chat.app import main as serve

    serve()
