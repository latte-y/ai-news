"""AI新聞 パイプライン一式（収集・検証・ビルド・通知）。

LLM/Claude API を呼び出すコードはこのパッケージには一切含めない。
翻訳・要約・記事選定は Claude Code の routine（ROUTINE.md）が対話的に行う。
"""

__version__ = "0.1.0"
